"""Synthetic API payloads built from the published OpenAPI examples."""

VIN_BEV = "TMBJB9NY5RF999999"
VIN_ICE = "TMBJB9NY5RF888888"

BEV = {
    "vehicle": {
        "vin": VIN_BEV,
        "name": "My Enyaq",
        "licensePlate": "1MB 1234",
        "renderUrl": "https://www.example.com/render.png",
        "status": {
            "overall": {
                "doorsLocked": "YES",
                "locked": "YES",
                "doors": "CLOSED",
                "windows": "OPEN",
                "lights": "OFF",
                "reliableLockStatus": "LOCKED",
            },
            "detail": {"sunroof": "CLOSED", "trunk": "OPEN", "bonnet": "CLOSED"},
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
        "odometer": {
            "mileageInKm": 12753,
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
        "parkingPosition": {
            "state": "PARKED",
            "gpsCoordinates": {"latitude": 37.4224428, "longitude": -122.0842467},
            "formattedAddress": "Prazska 4A, 10200 Prague, Czech Republic",
        },
        "airConditioning": {
            "state": "HEATING",
            "targetTemperature": {"value": 22.5, "unit": "CELSIUS"},
            "estimatedReachOfTargetTemperatureAt": "2026-06-12T07:40:00Z",
            "airConditioningWithoutExternalPower": True,
            "airConditioningAtUnlock": False,
            "windowHeating": {"enabled": True, "front": "ON", "rear": "OFF"},
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
        "auxiliaryHeating": {
            "state": "OFF",
            "startMode": "HEATING",
            "durationInSeconds": 600,
            "targetTemperature": {"value": 21.0, "unit": "CELSIUS"},
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
        "activeVentilation": {
            "state": "OFF",
            "durationInSeconds": 600,
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
        "charging": {
            "isVehicleInSavedLocation": True,
            "status": {
                "chargingRateInKilometersPerHour": 20.17,
                "chargePowerInKw": 11.0,
                "remainingTimeToFullyChargedInMinutes": 15,
                "fullyChargedAt": "2026-06-12T08:00:00Z",
                "state": "CHARGING",
                "chargeType": "AC",
                "battery": {
                    "remainingCruisingRangeInMeters": 249000,
                    "stateOfChargeInPercent": 71,
                },
            },
            "settings": {
                "targetStateOfChargeInPercent": 80,
                "batteryCareModeTargetValueInPercent": 80,
                "preferredChargeMode": "MANUAL",
                "availableChargeModes": ["MANUAL", "TIMER"],
                "chargingCareMode": "ACTIVATED",
                "autoUnlockPlugWhenCharged": "PERMANENT",
                "maxChargeCurrentAc": "MAXIMUM",
                "maxChargeCurrentAcAmpere": 32,
            },
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
        "chargingProfiles": {
            "profiles": [
                {
                    "id": 123456,
                    "name": "charging profile 1",
                    "settings": {
                        "maxChargingCurrent": "MAXIMUM",
                        "minBatteryStateOfCharge": {
                            "enabled": True,
                            "minimumBatteryStateOfChargeInPercent": 50,
                        },
                        "targetStateOfChargeInPercent": 80,
                        "autoUnlockPlugWhenCharged": "PERMANENT",
                    },
                    "preferredChargingTimes": [
                        {
                            "id": 1,
                            "enabled": True,
                            "startTime": "22:00",
                            "endTime": "06:00",
                        }
                    ],
                    "timers": [
                        {
                            "id": 1,
                            "enabled": True,
                            "time": "07:00",
                            "type": "RECURRING",
                            "recurringOn": ["MONDAY", "TUESDAY"],
                        }
                    ],
                }
            ],
            "currentVehiclePositionProfile": {
                "id": 123456,
                "name": "HOME",
                "targetStateOfChargeInPercent": 80,
                "nextChargingTime": "12:34",
            },
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
    },
    "errors": [],
}

ICE = {
    "vehicle": {
        "vin": VIN_ICE,
        "name": "My Octavia",
        "licensePlate": "1MB 4321",
        "status": {
            "overall": {
                "doorsLocked": "NO",
                "locked": "NO",
                "doors": "OPEN",
                "windows": "UNSUPPORTED",
                "lights": "ON",
            },
            "detail": {"sunroof": "UNSUPPORTED", "trunk": "CLOSED", "bonnet": "CLOSED"},
        },
        "odometer": {"mileageInKm": 88000},
        "fuelStatus": {
            "carType": "DIESEL",
            "adBlueRange": 1520,
            "totalRangeInKm": 520,
            "primaryEngineRange": {
                "engineType": "DIESEL",
                "currentFuelLevelInPercent": 87,
                "remainingRangeInKm": 520,
            },
            "carCapturedTimestamp": "2026-06-12T07:30:00Z",
        },
        "auxiliaryHeating": {"state": "HEATING_AUXILIARY", "startMode": "HEATING"},
    },
    "errors": [
        {
            "type": "CHARGING_UNSUPPORTED",
            "description": "Vehicle does not support charging.",
        }
    ],
}

RATE_LIMIT_HEADERS = {
    "X-API-Key-Expires-At": "2099-09-01T00:00:00Z",
    "RateLimit-Limit": "20",
    "RateLimit-Remaining": "18",
    "RateLimit-Reset": "1800",
}
