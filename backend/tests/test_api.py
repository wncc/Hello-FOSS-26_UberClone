from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .conftest import Actor, driver, rider, tick

PICKUP = {"lat": 12.9716, "lng": 77.5946, "address": "MG Road"}
DROP = {"lat": 12.9352, "lng": 77.6245, "address": "Koramangala"}


def book(r: Actor, vehicle: str = "car") -> dict:
    res = r.post("/rides", {"pickup": PICKUP, "drop": DROP, "vehicle_type": vehicle})
    assert res.status_code == 201, res.text
    return res.json()


# --------------------------------------------------------------------------- #
# Full ride
# --------------------------------------------------------------------------- #

def test_full_ride_lifecycle(client):
    r = rider(client)
    near = driver(client, 12.9726, 77.5946)            # ~110 m from pickup
    far = driver(client, 12.9800, 77.5946)             # ~930 m
    auto = driver(client, 12.9720, 77.5946, "auto_rickshaw")

    options = {o["vehicle_type"]: o for o in r.post("/rides/estimate", {"pickup": PICKUP, "drop": DROP}).json()["options"]}
    assert set(options) == {"car", "auto_rickshaw", "bike"}
    assert options["car"]["drivers_nearby"] == 2 and options["auto_rickshaw"]["drivers_nearby"] == 1
    assert options["bike"]["fare_paise"] < options["auto_rickshaw"]["fare_paise"] < options["car"]["fare_paise"]

    ride = book(r)
    assert ride["status"] == "searching" and len(ride["pin"]) == 4
    assert ride["fare_estimate_paise"] == options["car"]["fare_paise"]

    tick(client)
    assert near.events("ride:ping") and far.events("ride:ping")
    assert not auto.events("ride:ping")                 # wrong vehicle type
    assert near.get("/drivers/me/offer").json()["ride_id"] == ride["id"]
    assert "pin" not in near.events("ride:ping")[0]["data"]

    assert far.post(f"/rides/{ride['id']}/accept").status_code == 202
    assert near.post(f"/rides/{ride['id']}/accept").status_code == 202
    tick(client)                                         # nearest acceptor wins
    assigned = r.get(f"/rides/{ride['id']}").json()
    assert assigned["status"] == "driver_assigned" and assigned["driver"]["id"] == near.id
    assert near.events("ride:confirmed") and far.events("ride:taken")
    assert r.events("ride:driver_assigned")[0]["data"]["driver"]["id"] == near.id

    assert near.post("/drivers/me/location", {"lat": 12.9720, "lng": 77.5946}).status_code == 204
    assert r.events("driver:location")[-1]["data"]["lat"] == 12.9720
    assert near.post("/drivers/me/online", {"online": False}).status_code == 409   # mid-ride

    assert near.post(f"/rides/{ride['id']}/arrived").json()["status"] == "driver_arrived"
    driver_view = near.get(f"/rides/{ride['id']}").json()
    assert driver_view["pin"] is None                    # the driver must ask the rider
    wrong = "0000" if ride["pin"] != "0000" else "1111"
    assert near.post(f"/rides/{ride['id']}/start", {"pin": wrong}).status_code == 422
    assert near.post(f"/rides/{ride['id']}/start", {"pin": ride["pin"]}).json()["status"] == "in_progress"

    done = near.post(f"/rides/{ride['id']}/complete").json()
    assert done["status"] == "completed" and done["fare_final_paise"] == ride["fare_estimate_paise"]
    assert done["payment_status"] == "paid"              # cash, collected by the driver
    assert r.events("ride:completed")

    assert r.post(f"/rides/{ride['id']}/rating", {"stars": 5, "comment": "great"}).status_code == 201
    assert near.post(f"/rides/{ride['id']}/rating", {"stars": 4}).status_code == 201
    assert r.post(f"/rides/{ride['id']}/rating", {"stars": 1}).status_code == 409
    assert near.get("/me").json()["rating"] == 5.0 and r.get("/me").json()["rating"] == 4.0

    assert [x["id"] for x in r.get("/rides").json()] == [ride["id"]]
    assert [x["id"] for x in near.get("/rides").json()] == [ride["id"]]
    assert near.post("/drivers/me/online", {"online": False}).status_code == 200


# --------------------------------------------------------------------------- #
# Matching edge cases
# --------------------------------------------------------------------------- #

def test_driver_rejecting_is_not_pinged_again(client):
    r = rider(client)
    a = driver(client, 12.9726, 77.5946)
    ride = book(r)
    tick(client)
    assert a.post(f"/rides/{ride['id']}/reject").status_code == 204
    b = driver(client, 12.9730, 77.5946)
    tick(client)
    assert len(a.events("ride:ping")) == 1
    assert b.events("ride:ping")


def test_unanswered_ping_times_out(client):
    r = rider(client)
    a = driver(client, 12.9726, 77.5946)
    ride = book(r)
    tick(client)
    later = datetime.now(timezone.utc) + timedelta(seconds=25)
    tick(client, later)
    assert a.events("ride:ping_cancelled")
    assert len(a.events("ride:ping")) == 1               # not re-pinged for a ride they let lapse
    assert a.post(f"/rides/{ride['id']}/accept").status_code == 409


def test_no_drivers_after_search_timeout(client):
    r = rider(client)
    ride = book(r)
    tick(client, datetime.now(timezone.utc) + timedelta(minutes=4))
    assert r.get(f"/rides/{ride['id']}").json()["status"] == "no_drivers"
    assert r.events("ride:no_drivers")
    assert r.get("/rides/active").json() is None


def test_drivers_with_stale_gps_are_not_pinged(client):
    r = rider(client)
    a = driver(client, 12.9726, 77.5946)
    book(r)
    tick(client, datetime.now(timezone.utc) + timedelta(minutes=2))
    assert not a.events("ride:ping")


def test_rider_cancel_releases_pinged_drivers(client):
    r = rider(client)
    a = driver(client, 12.9726, 77.5946)
    ride = book(r)
    tick(client)
    assert r.post(f"/rides/{ride['id']}/cancel", {"reason": "changed plans"}).json()["status"] == "cancelled"
    assert a.events("ride:ping_cancelled")
    assert a.post(f"/rides/{ride['id']}/accept").status_code == 409


def test_driver_cancel_sends_ride_back_to_searching(client):
    r = rider(client)
    a = driver(client, 12.9726, 77.5946)
    ride = book(r)
    tick(client)
    a.post(f"/rides/{ride['id']}/accept")
    tick(client)
    assert a.post(f"/rides/{ride['id']}/cancel", {"reason": "flat tyre"}).json()["status"] == "searching"
    assert r.events("ride:driver_cancelled")
    b = driver(client, 12.9730, 77.5946)
    tick(client)
    assert b.events("ride:ping") and len(a.events("ride:ping")) == 1


def test_one_active_ride_per_rider(client):
    r = rider(client)
    book(r)
    res = r.post("/rides", {"pickup": PICKUP, "drop": DROP, "vehicle_type": "car"})
    assert res.status_code == 409


def test_online_payment_not_yet_available(client):
    r = rider(client)
    res = r.post("/rides", {"pickup": PICKUP, "drop": DROP, "vehicle_type": "car", "payment_method": "online"})
    assert res.status_code == 422


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def test_otp_rules(client):
    assert client.post("/auth/otp/request", json={"phone": "12345"}).status_code == 422
    phone = "98450 12345"
    code = client.post("/auth/otp/request", json={"phone": phone}).json()["dev_code"]
    for _ in range(5):
        assert client.post("/auth/otp/verify", json={"phone": phone, "code": "000000"}).status_code == 401
    assert client.post("/auth/otp/verify", json={"phone": phone, "code": code}).status_code == 429
    code = client.post("/auth/otp/request", json={"phone": phone}).json()["dev_code"]
    body = client.post("/auth/otp/verify", json={"phone": phone, "code": code}).json()
    assert body["user"]["phone"] == "+919845012345"
    refreshed = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refreshed.status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": body["access_token"]}).status_code == 401


def test_one_role_per_number(client):
    r = rider(client)
    code = client.post("/auth/otp/request", json={"phone": r.phone}).json()["dev_code"]
    res = client.post("/auth/otp/verify", json={"phone": r.phone, "code": code, "role": "driver"})
    assert res.status_code == 409


def test_roles_are_enforced(client):
    r = rider(client)
    d = driver(client, 12.97, 77.59)
    assert r.put("/drivers/me", {"vehicle_type": "car", "vehicle_number": "KA01AB1234"}).status_code == 403
    assert d.post("/rides", {"pickup": PICKUP, "drop": DROP, "vehicle_type": "car"}).status_code == 403
    assert r.get("/admin/rides").status_code == 403
    assert client.get("/me").status_code == 401


# --------------------------------------------------------------------------- #
# Admin approval
# --------------------------------------------------------------------------- #

def test_admin_approves_pending_driver(make_client):
    client = make_client(auto_approve_drivers=False, admin_phones=("+919999999999",))
    admin = Actor(client, "rider", phone="+919999999999")
    d = Actor(client, "driver")
    assert d.put("/drivers/me", {"vehicle_type": "bike", "vehicle_number": "KA01AB1234"}).json()["status"] == "pending"
    assert d.post("/drivers/me/online", {"online": True}).status_code == 403
    pending = admin.get("/admin/drivers", params={"status": "pending"}).json()
    assert [p["user_id"] for p in pending] == [d.id]
    assert admin.post(f"/admin/drivers/{d.id}/approve").json()["status"] == "approved"
    assert d.post("/drivers/me/online", {"online": True}).status_code == 200


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #

def test_websocket_events_and_driver_location(client):
    r = rider(client)
    d = driver(client, 12.9726, 77.5946)
    ride = book(r)
    with client.websocket_connect(f"/ws?token={r.token}") as rider_ws, \
            client.websocket_connect(f"/ws?token={d.token}") as driver_ws:
        tick(client)
        ping = driver_ws.receive_json()
        assert ping["event"] == "ride:ping" and ping["data"]["ride_id"] == ride["id"]
        d.post(f"/rides/{ride['id']}/accept")
        tick(client)
        assert rider_ws.receive_json()["event"] == "ride:driver_assigned"
        assert driver_ws.receive_json()["event"] == "ride:confirmed"
        driver_ws.send_json({"type": "location", "lat": 12.9722, "lng": 77.5946, "heading": 180})
        loc = rider_ws.receive_json()
        assert loc["event"] == "driver:location" and loc["data"]["lat"] == 12.9722


def test_websocket_rejects_bad_token(client):
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/ws?token=nope") as ws:
            ws.receive_json()
        raise AssertionError("expected the socket to close")
    except WebSocketDisconnect as e:
        assert e.code == 4401


# --------------------------------------------------------------------------- #
# Road routing (regression: routes used to be drawn as straight lines)
# --------------------------------------------------------------------------- #

def test_routes_follow_the_roads(make_client):
    from backend.app.services.routes import RouteService
    from routing import EdgeMeta, MultiVehicleRouter, RoadClass, TurnRestrictions, VehicleType
    from routing.graph import haversine_m

    # An L-shaped street: west->east along 12.9716, then north along 77.6046. No diagonal road.
    a, corner, c = (12.9716, 77.5946), (12.9716, 77.6046), (12.9816, 77.6046)
    def edges_for(v):
        return {s: EdgeMeta(s, x, y, RoadClass.PRIMARY, haversine_m(p, q), geometry=(p, q))
                for s, x, y, p, q in (("AB", "A", "B", a, corner), ("BC", "B", "C", corner, c))}

    class Extract:
        edges = {v: edges_for(v) for v in VehicleType}
        zones = []
        turn_restrictions = {v: TurnRestrictions() for v in VehicleType}

    client = make_client()
    client.app.state.ctx.routes = RouteService(MultiVehicleRouter.local(Extract()))
    r = rider(client)
    pickup, drop = {"lat": a[0], "lng": a[1]}, {"lat": c[0], "lng": c[1]}
    car = next(o for o in r.post("/rides/estimate", {"pickup": pickup, "drop": drop}).json()["options"]
               if o["vehicle_type"] == "car")
    assert [tuple(p) for p in car["route"]] == [a, corner, c]          # turns at the corner
    assert car["distance_m"] > haversine_m(a, c) * 1.3                  # road distance, not crow-flies

    ride = r.post("/rides", {"pickup": pickup, "drop": drop, "vehicle_type": "car"}).json()
    route = r.get(f"/rides/{ride['id']}/route").json()
    assert [tuple(p) for p in route["trip"]] == [a, corner, c]
    assert route["approach"] is None                                   # no driver yet

    far = {"lat": 13.5, "lng": 77.6}                                    # nowhere near the mapped roads
    res = r.post("/rides/estimate", {"pickup": pickup, "drop": far})
    assert res.status_code == 422 and "outside" in res.json()["detail"]
