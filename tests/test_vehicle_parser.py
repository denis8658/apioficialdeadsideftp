import json

from app.parsers.vehicle import VehicleParser, public_vehicle_data


def test_vehicle_parser_checks_vehicle_keys_and_count():
    payload = {"Count": 1, "Vehicle0": {"ActorID": "BP_SFPSVehicle_UAZ_Hunter_C", "X": -362088, "Y": -152570, "Z": -22634.4, "qZ": 0.65, "Vehicle": {"Fuel": 1002, "Drb": 88, "LockValue": 2, "LockPassword": "secret", "VehicleUID": "UID-1", "Inventory": {"Item0": {"Index": 2}}}}, "Vehicle2": {"ActorID": "BP_SFPSVehicle_Boat_C", "X": 1, "Y": 2, "Vehicle": {"VehicleUID": "UID-2"}}}
    result = VehicleParser().parse(json.dumps(payload).encode(), "new_vehicles.sav")
    assert len(result.entities) == 2
    assert result.warnings == ["Count=1 but found 2 VehicleN objects"]
    vehicle = result.entities[0]
    assert vehicle["vehicle_uid"] == "UID-1"
    assert vehicle["display_name"] == "UAZ Hunter"
    assert vehicle["durability"] == 88.0
    assert "LockPassword" not in vehicle["metadata"]
    assert "LockPassword" not in vehicle["raw_data"]["Vehicle"]


def test_public_vehicle_data_recursively_removes_secrets():
    assert public_vehicle_data({"a": {"LockPassword": "x", "ok": 1}, "token": "y"}) == {"a": {"ok": 1}}
