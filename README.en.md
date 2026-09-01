# MySkoda PublicAPI — Home Assistant Integration

**Language:** English | [Deutsch](README.md)

Home Assistant integration for the **official MyŠkoda Public API**
([docs](https://public.api.connect.skoda-auto.cz/docs) ·
[API reference](https://public.api.connect.skoda-auto.cz/docs/swagger-ui/index.html)).

The integration uses only the documented, public endpoint with an **API key from the
MyŠkoda app** — no credentials, no internal endpoints, no external Python dependencies.

> **Status: read paths verified against a real vehicle, remote commands not yet.**
> The API is in beta (`1.0.0-beta.6`). Verified with a real API key: the full vehicle
> request, the partial request `?include=info`, the behaviour for a VIN that is not
> covered, the `RateLimit-*` and expiry headers, and the absence of a vehicle-list
> endpoint. The response of a real Enyaq ships anonymised as a test fixture. **Not**
> exercised are the eight `POST` commands — those would actually operate the vehicle.

---

## How this differs from `homeassistant-myskoda`

| | [skodaconnect/homeassistant-myskoda](https://github.com/skodaconnect/homeassistant-myskoda) | **MySkoda PublicAPI** |
|---|---|---|
| Access | unofficial app API, email + password | official Public API, API key |
| Push | MQTT events, near real time | no, polling only |
| Rate limit | practically none | **20 requests/hour per key** |
| Scope | very large (trips, maintenance, score …) | limited to what the Public API offers |
| Dependency | `myskoda` PyPI package | none |

Both integrations can run side by side — they use different domains
(`myskoda` vs. `myskoda_publicapi`).

---

## Requirements

* Home Assistant **2025.3.0** or newer
* A connected Škoda vehicle
* An API key from the MyŠkoda app: **[go.skoda.eu/api-keys](https://go.skoda.eu/api-keys)**
  (open the link on your phone, the app manages the keys)

A key is **bound to the vehicles selected when it was created**, and it **expires**. The
integration reads the expiry date from every response and warns in time (sensor *API key
expires at*, problem sensor *API key expiring*). Once the key has expired, Home Assistant
starts the reauth dialog automatically.

## Installation

**HACS (recommended)** — HACS → ⋮ → *Custom repositories* → add this repository with
category *Integration* → install *MySkoda PublicAPI* → restart Home Assistant.

**Manual** — copy `custom_components/myskoda_publicapi` to `<config>/custom_components/`
and restart Home Assistant.

## Setup

*Settings → Devices & services → Add integration → **MySkoda PublicAPI***

1. **API key** — the only required value.
2. **Vehicles (VIN)** — this step exists only because the Public API offers **no endpoint
   to list the vehicles** of a key; there is only `GET /api/v1/vehicles/{vin}`. Verified
   with a valid key: `GET /api/v1/vehicles` answers with `404 No static resource`. The
   integration still tries it first on every setup — should Škoda ever return a list
   there, the step disappears automatically and setup really does ask for the API key
   only.

Every VIN you enter is validated against the API immediately, so typos and vehicles that
are not covered show up right in the dialog.

## Options

*Devices & services → MySkoda PublicAPI → **Configure***

| Option | Default | Meaning |
|---|---|---|
| Polling interval | 30 min | 5–1440 minutes. The dialog shows how many requests/hour the current setting consumes. Also changeable as an entity from automations — see below. |
| S-PIN | empty | Only needed for the **auxiliary heating** — the API requires it in the start call. Everything else works without an S-PIN. |
| Refresh after command | on | Polls once ~30 s after a remote command so the new state arrives promptly. Skipped when fewer than 3 requests are left in the quota. |

## Controlling the polling interval from automations

The interval is also an entity — `number.<api-device>_polling_interval` on the service
device *MySkoda PublicAPI*. That lets you change it via `number.set_value` from an
automation, for example to poll more often while charging and go back afterwards. The
value ends up in the same options as via the dialog and therefore survives a restart.

```yaml
automation:
  - alias: Poll MyŠkoda faster while charging
    triggers:
      - trigger: state
        entity_id: binary_sensor.my_enyaq_charging
        to: "on"
    actions:
      - action: number.set_value
        target:
          entity_id: number.myskoda_publicapi_polling_interval
        data:
          value: 5

  - alias: MyŠkoda back to the normal interval
    triggers:
      - trigger: state
        entity_id: binary_sensor.my_enyaq_charging
        to: "off"
        for: "00:10:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.myskoda_publicapi_polling_interval
        data:
          value: 30
```

**Shortening** the interval costs one request, because otherwise Home Assistant would only
reschedule the timer after the poll that is already planned. **Lengthening** it is free —
the next poll, still due on the short cadence, reschedules the timer itself. When the quota
is nearly empty, shortening is not armed immediately either, but on the next poll.

One catch remains: if the start of charging is triggered from a MyŠkoda entity, you learn
about it at the next poll at the earliest — with 30 minutes, up to 30 minutes too late. If
you have a source outside the integration that knows the start of charging right away — a
wallbox, an energy meter, or your own charge monitoring — use that as the trigger. The
short interval then applies from the first minute.

## Rate limit — please read

Škoda allows **20 requests per hour per API key**, shared across *all* vehicles and *all*
remote commands. The integration is built for that:

* **one** coordinator per config entry, which polls all vehicles one after another
* evaluation of the `RateLimit-*` headers after every response
* automatic backoff of polling on `429`, driven by `Retry-After`
* diagnostic entities for quota, reset time, and key expiry

Rule of thumb: `60 / interval × number of vehicles` requests per hour for polling — the
rest stays available for remote commands. With two vehicles and 30 minutes that is 4 out
of 20.

Error responses with `401`/`403` do not consume quota, all others — including `5xx` — do.

## Entities

Every vehicle becomes its own device; on top of that there is a service device *MySkoda
PublicAPI* for quota and key status. Entities are only created when the vehicle actually
delivers the corresponding data section — a diesel gets no charging entities, a BEV no
fuel entities.

**Every entity carries the complete raw data section as an attribute.** Everything without
a dedicated entity — and everything Škoda still adds during the beta — is therefore
available in Home Assistant without a code change.

<details>
<summary><b>Sensors</b> (up to 70)</summary>

* **Vehicle** — license plate, VIN, mileage, time of the last poll, number of data errors
* **Fuel** (`fuelStatus`) — car type, total range, AdBlue range, plus engine type, range,
  fuel level, and state of charge for the primary and secondary engine
* **Charging** (`charging`) — charging state, charge type, charging power, charging rate,
  remaining charging time, "fully charged at", battery state of charge, electric range,
  target state of charge, battery care, plug unlocking, maximum charge current (level and
  amperes)
* **Air conditioning** (`airConditioning`) — state, target temperature, expected time the
  target is reached, front/rear window heating
* **Auxiliary heating** (`auxiliaryHeating`) — state, start mode, duration, target
  temperature
* **Active ventilation** (`activeVentilation`) — state, duration
* **Vehicle status** (`status`) — lock state, doors, windows, lights, reliable lock status,
  sunroof, trunk, bonnet
* **Parking** (`parkingPosition`) — parking state, address
* **Charging profiles** (`chargingProfiles`) — number of profiles (details as an
  attribute), current profile, its target state of charge, and next charging time
* **API** — requests remaining, limit, reset time, API key expiry
* per data section additionally the `carCapturedTimestamp` (disabled by default)

</details>

<details>
<summary><b>Binary sensors</b> (up to 21)</summary>

Doors locked · doors · windows · lights · sunroof · trunk · bonnet · charging · charging
cable · at a saved location · air conditioning running · window heating enabled ·
front/rear window heating · air conditioning without external power · air conditioning at
unlock · auxiliary heating running · active ventilation running · in motion · API key
expiring · rate limit reached

</details>

<details>
<summary><b>Controls</b></summary>

| Platform | Entities |
|---|---|
| `switch` | charging, air conditioning, auxiliary heating, active ventilation, "allow air conditioning without external power" |
| `climate` | air conditioning (target temperature, on/off), auxiliary heating (target temperature, preset heating/ventilation) |
| `number` | target temperature, auxiliary heating duration |
| `select` | auxiliary heating start mode |
| `button` | refresh + one start/stop button per function (disabled by default) |
| `device_tracker` | parking position (GPS, address as an attribute) |
| `image` | vehicle render from `renderUrl` |

`number`, `select`, and the "without external power" switch write **nothing** to the
vehicle — the API has no endpoints for changing settings. They hold the values Home
Assistant sends along with the **next start command**, and are restored across restarts.

</details>

## Actions (services)

`myskoda_publicapi.refresh` · `start_charging` · `stop_charging` · `start_air_conditioning` ·
`stop_air_conditioning` · `start_auxiliary_heating` · `stop_auxiliary_heating` ·
`start_active_ventilation` · `stop_active_ventilation`

Target either via the `device_id` field or `vin`. Without a target the action applies to
all configured vehicles.

```yaml
action: myskoda_publicapi.start_air_conditioning
data:
  device_id: <vehicle>
  temperature: 22
  without_external_power: true
```

```yaml
action: myskoda_publicapi.start_auxiliary_heating
data:
  vin: TMBJB9NY5RF999999
  temperature: 21.5
  duration: 20
  start_mode: heating
  spin: "1234"   # optional, otherwise taken from the options
```

## Limits of the API

Not possible, because the Public API does not (yet) offer it:

* **Locking/unlocking**, honking, flashing the lights — status only, no `lock` endpoint
* **Writing settings** — target state of charge, charge current, charging profiles, and
  timers are read-only
* **Trips, maintenance, vehicle score, software version, outside temperature** — not part
  of the Public API
* **Vehicle list for an API key** — hence the VIN step during setup
* **Push/real time** — the API offers neither MQTT nor webhooks

Responses with status `200` can be incomplete: sections that are unsupported or currently
unavailable are missing and described in the `errors` list. That list is attached to the
sensor *Data errors*.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Reauth dialog appears | key expired or revoked (`401`) | create a new key in the MyŠkoda app |
| "The API key is not valid for this vehicle" | key does not cover the VIN (`403`) | recreate the key with the vehicle included |
| Entities become `unavailable` | quota exhausted (`429`) | increase the interval; the integration backs off automatically |
| Command fails with "not possible" | `422` — function missing or disabled | retrying does not help; check the equipment or activation |
| Auxiliary heating cannot be switched | S-PIN missing | store the S-PIN in the options |

Debug logging:

```yaml
logger:
  logs:
    custom_components.myskoda_publicapi: debug
```

For bug reports: *Devices & services → MySkoda PublicAPI → ⋮ → Download diagnostics*. VIN,
license plate, address, and GPS position are removed automatically.

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).

Not an official Škoda Auto product. Škoda and MyŠkoda are trademarks of Škoda Auto a.s.

## Tests

In the tests the integration runs against a real Home Assistant. 76 tests cover the config
flow, reauth, options, entity creation for BEV and combustion engines, all remote commands,
rate-limit backoff, error cases (401/403/422/429), restoration after a restart, the
diagnostics redaction, and the rules that `hassfest` and HACS check.

Part of that runs against the **anonymised response of a real Enyaq**
(`tests/fixture_real_enyaq.json`): which sections the vehicle reports, which fields it
omits, the actual enum values, and the mixed timestamp formats are taken over unchanged.

```bash
pip install -r requirements-test.txt && pytest -q
```

What this does **not** cover: the eight `POST` commands against a real vehicle, the
behaviour when the quota is exhausted (`429`), and reauth with an actually expired key.
