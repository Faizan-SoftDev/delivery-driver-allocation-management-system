from delivery_system import (
    CONFIG, additional_reports, allocate_driver, allocate_pending_tasks, assign_driver,
    build_starter_deliveries, build_starter_drivers, calculate_delivery_charge,
    calculate_driver_earning, calculate_total, dashboard_data, driver_performance_report,
    explain_legb_demo, format_money, format_percent, make_rate_calculator,
    render_additional_reports, render_dashboard, task_delivery_charge, task_driver_earning,
    update_delivery_status, validate_driver, validate_task, zone_report,
)

def starter():
    return build_starter_drivers(), build_starter_deliveries()


def make_task(task_id="T1", **changes):
    task = {"id": task_id, "customer": "Test", "zone": "A", "distance": 4,
            "order_amount": 120, "priority": "normal", "status": "pending", "driver_id": None}
    task.update(changes)
    return task


def make_driver(zone="A", rating=4.5, available=True, name="Test"):
    return {"name": name, "zone": zone, "available": available, "rating": rating}


def demo_state():
    """Same story as main(): D001 delivered TASK001, D004 failed TASK003,
    D002 still on TASK002, plus an unservable zone-C task."""
    drivers, tasks = starter()
    allocate_pending_tasks(drivers, tasks)
    for task_id, final in (("TASK001", "delivered"), ("TASK003", "failed")):
        update_delivery_status(drivers, tasks, task_id, "picked_up")
        update_delivery_status(drivers, tasks, task_id, final)
    tasks.append(make_task("TASK004", zone="C", distance=0, order_amount=50))
    return drivers, tasks

def test_fresh_starter_data():
    first, second = build_starter_drivers(), build_starter_drivers()
    first["D001"]["available"] = False
    assert second["D001"]["available"] is True
    one, two = build_starter_deliveries(), build_starter_deliveries()
    one[0]["driver_id"] = "D001"
    assert two[0]["driver_id"] is None
    assert all("driver_id" in task for task in two)

def test_allocation_picks_highest_rating():
    drivers, tasks = starter()
    outcome = allocate_driver(drivers, tasks, "TASK001")
    assert outcome["success"] and outcome["data"]["driver_id"] == "D001"  # 4.8 beats 4.2
    assert tasks[0]["status"] == "assigned" and tasks[0]["driver_id"] == "D001"
    assert drivers["D001"]["available"] is False


def test_allocation_respects_zone_and_availability():
    drivers, tasks = starter()
    # D003 has the best rating (4.9) in zone A but is unavailable; D002 is zone B.
    assert allocate_driver(drivers, tasks, "TASK003")["data"]["driver_id"] == "D001"
    assert allocate_driver(drivers, tasks, "TASK002")["data"]["driver_id"] == "D002"
    assert drivers["D003"]["available"] is False


def test_tie_break_lowest_driver_id():
    drivers = {"D004": make_driver(rating=4.5), "D001": make_driver(rating=4.5),
               "D002": make_driver(rating=4.5)}
    tasks = [make_task()]
    assert allocate_driver(drivers, tasks, "T1")["data"]["driver_id"] == "D001"
    drivers = {"D004": make_driver(rating=4.5), "D001": make_driver(rating=4.5)}
    batch = allocate_pending_tasks(drivers, [make_task("T1"), make_task("T2")])
    assert [item["driver_id"] for item in batch["data"]["assigned"]] == ["D001", "D004"]


def test_no_driver_in_zone():
    drivers, tasks = starter()
    tasks.append(make_task("TASK009", zone="C"))
    outcome = allocate_driver(drivers, tasks, "TASK009")
    assert outcome["success"] is False
    assert outcome["message"] == "No available driver exists in zone C."
    assert tasks[-1]["status"] == "pending" and tasks[-1]["driver_id"] is None
    assert drivers == build_starter_drivers()


def test_already_assigned_task_rejected():
    drivers, tasks = starter()
    assert assign_driver(drivers, tasks, "TASK001", "D001")["success"]
    for operation in (allocate_driver(drivers, tasks, "TASK001"),
                      assign_driver(drivers, tasks, "TASK001", "D004")):
        assert operation["success"] is False
        assert operation["message"] == "Task TASK001 has already been assigned."
    assert tasks[0]["driver_id"] == "D001" and drivers["D004"]["available"] is True


def test_busy_driver_rejected():
    drivers, tasks = starter()
    outcome = assign_driver(drivers, tasks, "TASK001", "D003")  # flagged unavailable
    assert outcome["message"] == "Driver D003 is currently busy."
    assert assign_driver(drivers, tasks, "TASK001", "D001")["success"]
    outcome = assign_driver(drivers, tasks, "TASK003", "D001")  # now busy with TASK001
    assert outcome["message"] == "Driver D001 is currently busy."
    assert tasks[2]["status"] == "pending"


def test_assign_driver_rejections():
    drivers, tasks = starter()
    assert assign_driver(drivers, tasks, "TASK999", "D001")["message"] == "Task TASK999 not found."
    assert assign_driver(drivers, tasks, "TASK001", "D999")["message"] == "Driver D999 not found."
    wrong_zone = assign_driver(drivers, tasks, "TASK001", "D002")
    assert wrong_zone["success"] is False and "requires zone A" in wrong_zone["message"]
    for bad_id in (None, 5, ["TASK001"], {"a": 1}):
        assert assign_driver(drivers, tasks, bad_id, "D001")["success"] is False
        assert assign_driver(drivers, tasks, "TASK001", bad_id)["success"] is False
        assert allocate_driver(drivers, tasks, bad_id)["success"] is False
        assert update_delivery_status(drivers, tasks, bad_id, "picked_up")["success"] is False
    assert drivers == build_starter_drivers() and tasks == build_starter_deliveries()


def test_batch_urgent_first_and_multiple_allocations():
    drivers, tasks = starter()
    batch = allocate_pending_tasks(drivers, tasks)
    assert batch["success"]
    order = [(item["task_id"], item["driver_id"]) for item in batch["data"]["assigned"]]
    assert order == [("TASK002", "D002"), ("TASK001", "D001"), ("TASK003", "D004")]
    assert batch["data"]["unassigned"] == []
    # one zone-A driver, urgent task must win him over the normal one
    drivers = {"D001": make_driver()}
    tasks = [make_task("A_NORMAL"), make_task("Z_URGENT", priority="urgent")]
    batch = allocate_pending_tasks(drivers, tasks)
    assert batch["data"]["assigned"] == [{"task_id": "Z_URGENT", "driver_id": "D001"}]
    assert batch["data"]["unassigned"][0]["task_id"] == "A_NORMAL"


def test_batch_equals_repeated_single_allocation():
    drivers_a, tasks_a = starter()
    drivers_b, tasks_b = starter()
    extra = [make_task("TASK004", zone="A", priority="urgent"), make_task("TASK005", zone="B")]
    tasks_a.extend(extra)
    tasks_b.extend([dict(task) for task in extra])
    allocate_pending_tasks(drivers_a, tasks_a)
    for task_id in ("TASK002", "TASK004", "TASK001", "TASK003", "TASK005"):  # urgent first, then ID
        allocate_driver(drivers_b, tasks_b, task_id)
    assert tasks_a == tasks_b and drivers_a == drivers_b


def test_single_active_task_rule():
    # D001 is flagged available but already has an active task -> not eligible.
    drivers = {"D001": make_driver(available=True)}
    tasks = [make_task("T1", status="assigned", driver_id="D001"), make_task("T2")]
    assert allocate_driver(drivers, tasks, "T2")["success"] is False
    assert assign_driver(drivers, tasks, "T2", "D001")["message"] == "Driver D001 is currently busy."

def test_delivery_charge_boundaries():
    expected = {0: 5.0, 4: 9.0, 5: 10.0, 5.5: 13.25, 6: 14.0, 7: 15.5, 10: 20.0, 11: 27.0, 12: 29.0}
    for km, final in expected.items():
        assert calculate_delivery_charge(km, "normal")["data"]["final_charge"] == final, km
    assert calculate_delivery_charge(12, "urgent")["data"]["final_charge"] == 36.25
    assert calculate_delivery_charge(0, "urgent")["data"]["final_charge"] == 6.25


def test_delivery_charge_breakdown():
    data = calculate_delivery_charge(4, "urgent")["data"]
    assert data == {"base": 5.0, "distance": 4.0, "rate": 1.0, "distance_charge": 4.0,
                    "surcharge": 2.25, "final_charge": 11.25}
    normal = calculate_delivery_charge(4, "normal")["data"]
    assert normal["surcharge"] == 0.0
    assert calculate_delivery_charge("4", " URGENT ")["data"]["final_charge"] == 11.25


def test_delivery_charge_kwargs():
    assert calculate_delivery_charge(1, "normal", base_charge=10)["data"]["final_charge"] == 11.0
    assert calculate_delivery_charge(4, "urgent", urgent_surcharge=0.5)["data"]["final_charge"] == 13.5
    assert calculate_delivery_charge(4, "normal", urgent_surcharge=0.5)["data"]["final_charge"] == 9.0
    unknown = calculate_delivery_charge(1, "normal", bogus=1)
    assert unknown["success"] is False and unknown["message"] == "Unknown pricing option: bogus."
    assert calculate_delivery_charge(1, "normal", driver_base=3)["success"] is False  # wrong function
    for bad in (-1, "5", True, float("nan"), float("inf"), None):
        assert calculate_delivery_charge(1, "normal", base_charge=bad)["success"] is False
    assert CONFIG["base_charge"] == 5.0 and CONFIG["urgent_surcharge"] == 0.25  # CONFIG untouched


def test_delivery_charge_invalid_input():
    assert calculate_delivery_charge(-5, "normal")["message"] == "Invalid distance: -5."
    for bad in (True, "abc", "", None, float("nan"), float("inf"), [], 10 ** 400):
        assert calculate_delivery_charge(bad, "normal")["success"] is False, bad
    assert calculate_delivery_charge(3, "super_urgent")["message"] == "Invalid priority: super_urgent."
    assert calculate_delivery_charge(3, None)["success"] is False

def test_driver_earning_distance_brackets():
    expected = {0: 3.0, 4: 6.2, 5: 7.0, 6: 10.2, 10: 15.0, 11: 19.5}
    for km, total in expected.items():
        assert calculate_driver_earning(km, 100)["data"]["total"] == total, km


def test_driver_earning_bonus_threshold():
    assert calculate_driver_earning(0, 149.99)["data"]["total"] == 3.0
    assert calculate_driver_earning(0, 150)["data"]["total"] == 3.3
    assert calculate_driver_earning(7, 200)["data"]["total"] == 12.54
    data = calculate_driver_earning(7, 200)["data"]
    assert data == {"base": 3.0, "distance": 7.0, "rate": 1.2, "distance_earning": 8.4,
                    "bonus": 1.14, "total": 12.54}


def test_driver_earning_kwargs_and_invalid_input():
    custom = calculate_driver_earning(1, 100, driver_base=4, bonus_threshold=100, driver_bonus_percentage=0.2)
    assert custom["data"]["total"] == 5.76
    assert calculate_driver_earning(1, 100, odd=1)["success"] is False
    assert calculate_driver_earning(1, 100, base_charge=5)["success"] is False
    for bad in (0, -1, "x", True, None, float("nan")):
        assert calculate_driver_earning(1, bad)["success"] is False, bad
    assert calculate_driver_earning(-1, 100)["message"] == "Invalid distance: -1."


def test_failed_task_earns_zero():
    assert task_driver_earning(make_task(status="failed", driver_id="D001"))["data"]["total"] == 0.0
    assert task_driver_earning(make_task(status="delivered", driver_id="D001"))["data"]["total"] == 6.2
    assert task_driver_earning({"id": "x"})["success"] is False
    assert task_delivery_charge(make_task(distance=-1))["success"] is False


def test_calculate_total_args():
    assert calculate_total(1, "2", 3.5)["data"] == 6.5
    assert calculate_total()["data"] == 0.0
    bad = calculate_total(1, "x", 3)
    assert bad["success"] is False and bad["message"] == "Invalid amount at position 2: x."
    for value in (True, None, float("nan"), float("inf"), [1], -0.01):
        assert calculate_total(1, value)["success"] is False
    assert calculate_total(0, 0)["data"] == 0.0
    assert calculate_total(5, -1)["message"] == "Invalid amount at position 2: -1."


def test_validate_task_accepts_and_normalises():
    assert validate_task(make_task())["success"]
    assert validate_task(make_task(distance=0))["success"]            # zero distance is valid
    assert validate_task(make_task(distance="4.5", order_amount="99"))["success"]
    assert validate_task(make_task(priority=" URGENT ", zone=" a ", status=" Pending "))["success"]


def test_validate_task_rejections():
    for field in ("id", "customer", "zone", "distance", "order_amount", "priority", "status"):
        broken = make_task()
        del broken[field]
        assert validate_task(broken)["message"] == "Missing task field: {}.".format(field)
    assert validate_task("nope")["success"] is False
    assert validate_task(None)["success"] is False
    for bad in (-1, True, "abc", float("nan"), float("inf"), None, [1]):
        assert validate_task(make_task(distance=bad))["success"] is False, bad
    for bad in (0, -2, False, "NaN", "x", float("inf"), None):
        assert validate_task(make_task(order_amount=bad))["success"] is False, bad
    assert validate_task(make_task(priority="super_urgent"))["message"] == "Invalid priority: super_urgent."
    assert validate_task(make_task(status="teleported"))["message"] == "Invalid status: teleported."
    assert validate_task(make_task(zone="  "))["success"] is False
    assert validate_task(make_task(task_id=""))["success"] is False
    assert validate_task(make_task(customer=5))["success"] is False
    assert validate_task(make_task(driver_id=7))["success"] is False


def test_validate_task_active_needs_known_driver():
    assert validate_task(make_task(status="assigned"))["success"] is False                  # no driver
    assert validate_task(make_task(status="picked_up", driver_id="D9"), {"D1"})["success"] is False
    assert validate_task(make_task(status="assigned", driver_id="D1"), {"D1"})["success"]


def test_validate_driver():
    assert validate_driver(make_driver())["success"]
    assert validate_driver(make_driver(rating=0))["success"] and validate_driver(make_driver(rating=5))["success"]
    for bad in (5.1, -0.1, "x", True, None, float("nan")):
        assert validate_driver(make_driver(rating=bad))["success"] is False, bad
    for bad in ("yes", 1, 0, None):
        assert validate_driver(make_driver(available=bad))["success"] is False, bad
    assert validate_driver(make_driver(zone=""))["success"] is False
    assert validate_driver(make_driver(name=" "))["success"] is False
    assert validate_driver({"name": "x"})["message"] == "Missing driver field: zone."
    assert validate_driver([])["success"] is False


def test_duplicate_and_invalid_records_are_skipped():
    drivers = {"D001": make_driver(), "BAD": {"name": "x"}, "D002": make_driver(rating=9)}
    tasks = [make_task("DUP"), make_task("DUP", zone="B"), make_task("BAD", distance=-1), "garbage", None]
    board = dashboard_data(drivers, tasks)["data"]
    assert board["total_tasks"] == 1
    assert len(board["rejected_tasks"]) == 4
    assert board["rejected_tasks"][0]["reason"] == "Duplicate task ID: DUP."
    assert len(board["rejected_drivers"]) == 2
    # valid work still goes through
    assert allocate_driver(drivers, tasks, "DUP")["data"]["driver_id"] == "D001"


def test_invalid_driver_record_is_reported_and_never_chosen():
    drivers = {"D001": make_driver(rating=99), "D002": make_driver(rating=3.0)}
    tasks = [make_task()]
    assert assign_driver(drivers, tasks, "T1", "D001")["message"].startswith("Driver D001 has invalid data:")
    assert allocate_driver(drivers, tasks, "T1")["data"]["driver_id"] == "D002"


def test_invalid_task_is_reported_by_id():
    drivers, tasks = starter()
    tasks[0]["distance"] = -3
    message = assign_driver(drivers, tasks, "TASK001", "D001")["message"]
    assert message == "Task TASK001 has invalid data: Invalid distance: -3."


def test_numeric_string_tasks_work_end_to_end():
    drivers = {"D001": make_driver()}
    tasks = [make_task(distance="4", order_amount="120")]
    assert allocate_driver(drivers, tasks, "T1")["success"]
    update_delivery_status(drivers, tasks, "T1", "picked_up")
    update_delivery_status(drivers, tasks, "T1", "delivered")
    board = dashboard_data(drivers, tasks)["data"]
    assert board["total_delivery_charges"] == 9.0 and board["total_order_value"] == 120.0


# --------------------------------------------------------------------------
# Workflow
# --------------------------------------------------------------------------
def test_full_workflow_delivered_releases_driver():
    drivers, tasks = starter()
    assert update_delivery_status(drivers, tasks, "TASK001", "picked_up")["success"] is False
    assert assign_driver(drivers, tasks, "TASK001", "D001")["success"]
    assert update_delivery_status(drivers, tasks, "TASK001", "picked_up")["success"]
    assert drivers["D001"]["available"] is False                      # still busy while picked up
    done = update_delivery_status(drivers, tasks, "TASK001", "delivered")
    assert done["success"] and done["data"]["driver_released"] == "D001"
    assert tasks[0]["status"] == "delivered" and drivers["D001"]["available"] is True


def test_failed_path_releases_driver():
    drivers, tasks = starter()
    assign_driver(drivers, tasks, "TASK001", "D001")
    update_delivery_status(drivers, tasks, "TASK001", "picked_up")
    assert update_delivery_status(drivers, tasks, "TASK001", "failed")["success"]
    assert tasks[0]["status"] == "failed" and drivers["D001"]["available"] is True


def test_every_invalid_transition_is_rejected_and_changes_nothing():
    statuses = ("pending", "assigned", "picked_up", "delivered", "failed")
    valid = {("assigned", "picked_up"), ("picked_up", "delivered"), ("picked_up", "failed")}
    checked = 0
    for old in statuses:
        for new in statuses:
            if (old, new) in valid:
                continue
            drivers = {"D001": make_driver(available=old not in ("assigned", "picked_up"))}
            driver_id = None if old == "pending" else "D001"
            tasks = [make_task(status=old, driver_id=driver_id)]
            outcome = update_delivery_status(drivers, tasks, "T1", new)
            assert outcome["success"] is False, (old, new)
            assert tasks[0]["status"] == old, (old, new)
            assert drivers["D001"]["available"] is (old not in ("assigned", "picked_up")), (old, new)
            checked += 1
    assert checked == 22
    drivers, tasks = {"D001": make_driver()}, [make_task()]
    assert update_delivery_status(drivers, tasks, "T1", "delivered")["message"] == \
        "Invalid status transition: pending -> delivered."
    assert "assign_driver" in update_delivery_status(drivers, tasks, "T1", "assigned")["message"]


def test_delivered_and_failed_tasks_cannot_be_reprocessed():
    drivers, tasks = starter()
    for task_id, final, text in (("TASK001", "delivered", "delivered"), ("TASK003", "failed", "failed")):
        assign_driver(drivers, tasks, task_id, "D001")
        update_delivery_status(drivers, tasks, task_id, "picked_up")
        update_delivery_status(drivers, tasks, task_id, final)
        expected = "Task {} has already been delivered.".format(task_id) if final == "delivered" \
            else "Task {} has already failed.".format(task_id)
        for outcome in (allocate_driver(drivers, tasks, task_id),
                        assign_driver(drivers, tasks, task_id, "D001"),
                        update_delivery_status(drivers, tasks, task_id, "pending"),
                        update_delivery_status(drivers, tasks, task_id, "assigned"),
                        update_delivery_status(drivers, tasks, task_id, final)):
            assert outcome["success"] is False and outcome["message"] == expected
    assert allocate_pending_tasks(drivers, tasks)["data"]["assigned"][0]["task_id"] == "TASK002"


def test_update_status_invalid_input():
    drivers, tasks = starter()
    assert update_delivery_status(drivers, tasks, "TASK999", "picked_up")["message"] == "Task TASK999 not found."
    assert update_delivery_status(drivers, tasks, "TASK001", "teleported")["message"] == "Invalid status: teleported."
    for bad in (None, 3, ["x"]):
        assert update_delivery_status(drivers, tasks, "TASK001", bad)["success"] is False


def test_failed_operations_do_not_mutate_data():
    drivers, tasks = starter()
    assign_driver(drivers, tasks, "TASK999", "D001")
    assign_driver(drivers, tasks, "TASK001", "D003")
    update_delivery_status(drivers, tasks, "TASK001", "delivered")
    calculate_delivery_charge(-1, "normal")
    assert drivers == build_starter_drivers() and tasks == build_starter_deliveries()

def test_driver_report_totals_zero_task_driver_and_completion():
    drivers = {"D001": make_driver(name="One"), "D002": make_driver(zone="B", name="Two")}
    tasks = [make_task("T1", status="delivered", driver_id="D001"),
             make_task("T2", status="failed", driver_id="D001", distance=7, order_amount=200)]
    rows = driver_performance_report(drivers, tasks)["data"]["drivers"]
    assert [row["driver_id"] for row in rows] == ["D001", "D002"]      # ranked by earnings
    first, idle = rows
    assert (first["total_assigned"], first["delivered"], first["failed"]) == (2, 1, 1)
    assert first["total_distance"] == 4.0 and first["total_earnings"] == 6.2   # delivered only
    assert first["completion_rate"] == 50.0
    assert idle["total_assigned"] == 0 and idle["completion_rate"] == 0.0 and idle["total_earnings"] == 0.0
    assert idle["name"] == "Two" and idle["zone"] == "B"


def test_zone_report_multiple_zones_ranked_by_revenue():
    drivers = {"D001": make_driver(zone="A"), "D002": make_driver(zone="B"), "D005": make_driver(zone="c")}
    tasks = [make_task("T1", zone="A", status="delivered", driver_id="D001"),
             make_task("T2", zone="B", distance=12, priority="urgent", status="delivered", driver_id="D002"),
             make_task("T3", zone="B")]
    rows = zone_report(drivers, tasks)["data"]["zones"]
    assert [row["zone"] for row in rows] == ["B", "A", "C"]
    by_zone = {row["zone"]: row for row in rows}
    assert by_zone["B"]["delivered_revenue"] == 36.25 and by_zone["B"]["total_tasks"] == 2
    assert by_zone["A"]["delivered_revenue"] == 9.0
    assert by_zone["C"]["total_tasks"] == 0 and by_zone["C"]["driver_count"] == 1


def test_additional_reports():
    drivers, tasks = demo_state()
    data = additional_reports(drivers, tasks)["data"]
    assert data["unique_zones"] == ["A", "B", "C"]
    assert data["tasks_per_zone"] == {"A": 2, "B": 1, "C": 1}
    assert data["revenue_per_zone"] == {"A": 9.0, "B": 0.0, "C": 0.0}
    assert data["average_order_amount"] == 112.5
    assert data["longest_delivery"] == {"task_id": "TASK002", "distance": 12.0}
    assert data["highest_value_order"] == {"task_id": "TASK003", "order_amount": 200.0}
    assert data["available_drivers"] == ["D001", "D004"]
    assert data["busy_drivers"] == ["D002", "D003"]
    assert data["urgent_deliveries"] == ["TASK002"]
    assert data["unassigned_tasks"] == [{"task_id": "TASK004",
                                         "reason": "No available driver exists in zone C."}]
    text = render_additional_reports(data)
    assert "Unique zones: A, B, C" in text and "- TASK004: No available driver exists in zone C." in text


def test_unassigned_reason_when_driver_is_available():
    drivers, tasks = starter()
    data = additional_reports(drivers, tasks)["data"]
    assert len(data["unassigned_tasks"]) == 3
    assert data["unassigned_tasks"][0]["reason"].startswith("Awaiting allocation")


def test_dashboard_values_and_exact_layout():
    drivers, tasks = demo_state()
    board = dashboard_data(drivers, tasks)["data"]
    assert board["total_tasks"] == 4
    assert board["status_counts"] == {"pending": 1, "assigned": 1, "picked_up": 0, "delivered": 1, "failed": 1}
    assert board["total_order_value"] == 450.0
    assert board["total_delivery_charges"] == 9.0
    assert board["total_driver_earnings"] == 6.2
    assert board["top_driver"] == {"driver_id": "D001", "name": "Ali"}
    assert board["highest_revenue_zone"] == "A"
    assert board["average_delivery_distance"] == 5.75
    assert board["unassigned_tasks"] == ["TASK004"]
    expected = "\n".join([
        "========== DELIVERY DASHBOARD ==========",
        "Total Tasks: 4", "Pending: 1", "Assigned: 1", "Picked Up: 0", "Delivered: 1", "Failed: 1",
        "Total Order Value: $450.00", "Total Delivery Charges: $9.00", "Total Driver Earnings: $6.20",
        "Top Driver: D001 (Ali)", "Highest Revenue Zone: A", "Average Delivery Distance: 5.75 km",
        "Unassigned Tasks:", "- TASK004",
        "========================================"])
    assert render_dashboard(board) == expected


def test_top_driver_tie_breaks():
    drivers = {"D002": make_driver(name="Two"), "D001": make_driver(name="One"), "D003": make_driver(name="Three")}
    # D001 and D002 each delivered one task with identical earnings -> lowest ID wins
    tasks = [make_task("T1", status="delivered", driver_id="D002"),
             make_task("T2", status="delivered", driver_id="D001")]
    assert dashboard_data(drivers, tasks)["data"]["top_driver"]["driver_id"] == "D001"
    # D003 delivers one bigger task -> same count, higher earnings wins
    tasks.append(make_task("T3", status="delivered", driver_id="D003", distance=12, order_amount=500))
    assert dashboard_data(drivers, tasks)["data"]["top_driver"]["driver_id"] == "D003"
    # D001 delivers two -> highest count wins regardless of earnings
    tasks.append(make_task("T4", status="delivered", driver_id="D001"))
    assert dashboard_data(drivers, tasks)["data"]["top_driver"]["driver_id"] == "D001"


def test_dashboard_revenue_zone_tie_is_alphabetical():
    drivers = {"D001": make_driver(zone="A"), "D002": make_driver(zone="B")}
    tasks = [make_task("T1", zone="B", status="delivered", driver_id="D002"),
             make_task("T2", zone="A", status="delivered", driver_id="D001")]
    assert dashboard_data(drivers, tasks)["data"]["highest_revenue_zone"] == "A"


def test_reports_share_one_ranking_and_set_based_zones():
    drivers, tasks = demo_state()
    zones = zone_report(drivers, tasks)["data"]["zones"]
    extra = additional_reports(drivers, tasks)["data"]
    assert [row["zone"] for row in zones] == ["A", "B", "C"]          # revenue desc, then A-Z
    assert extra["unique_zones"] == sorted(row["zone"] for row in zones)
    assert zones[-1]["driver_count"] == 0 and zones[-1]["total_tasks"] == 1   # task-only zone C
    assert dashboard_data(drivers, tasks)["data"]["highest_revenue_zone"] == zones[0]["zone"]

def test_empty_drivers_and_empty_deliveries():
    drivers, tasks = starter()
    assert allocate_driver({}, tasks, "TASK001")["message"] == "No available driver exists in zone A."
    batch = allocate_pending_tasks({}, tasks)
    assert batch["success"] and batch["data"]["assigned"] == [] and len(batch["data"]["unassigned"]) == 3
    assert assign_driver({}, tasks, "TASK001", "D001")["message"] == "Driver D001 not found."
    assert allocate_driver(drivers, [], "TASK001")["message"] == "Task TASK001 not found."
    assert allocate_pending_tasks(drivers, [])["data"] == {
        "assigned": [], "unassigned": [], "rejected_tasks": [], "rejected_drivers": []}
    assert driver_performance_report(drivers, [])["data"]["drivers"][0]["completion_rate"] == 0.0
    assert driver_performance_report({}, tasks)["data"]["drivers"] == []


def test_reports_on_completely_empty_data():
    assert zone_report({}, [])["data"]["zones"] == []
    extra = additional_reports({}, [])["data"]
    assert extra["unique_zones"] == [] and extra["average_order_amount"] == 0.0
    assert extra["longest_delivery"] is None and extra["highest_value_order"] is None
    assert extra["available_drivers"] == [] and extra["unassigned_tasks"] == []
    assert "Longest delivery: N/A" in render_additional_reports(extra)
    board = dashboard_data({}, [])["data"]
    assert board["total_tasks"] == 0 and board["top_driver"] is None
    assert board["highest_revenue_zone"] == "N/A" and board["average_delivery_distance"] == 0.0
    text = render_dashboard(board)
    assert "Top Driver: N/A" in text and "Average Delivery Distance: 0.00 km" in text and "- None" in text


def test_wrong_container_types_never_crash():
    drivers, tasks = starter()
    for bad in (None, 5, "x", [], ()):
        if not isinstance(bad, dict):
            assert dashboard_data(bad, tasks)["success"] is False
            assert allocate_pending_tasks(bad, tasks)["success"] is False
            assert assign_driver(bad, tasks, "TASK001", "D001")["success"] is False
            assert update_delivery_status(bad, tasks, "TASK001", "picked_up")["success"] is False
            assert driver_performance_report(bad, tasks)["success"] is False
            assert zone_report(bad, tasks)["success"] is False
            assert additional_reports(bad, tasks)["success"] is False
    for bad in (None, 5, "x", {}):
        assert dashboard_data(drivers, bad)["success"] is False
        assert allocate_driver(drivers, bad, "TASK001")["success"] is False

def test_closure_remembers_enclosing_values():
    cheap = make_rate_calculator(((5, 1.0), (None, 2.0)), 10)
    pricey = make_rate_calculator(((5, 3.0), (None, 4.0)), 0)
    assert cheap(3) == {"rate": 1.0, "distance_amount": 3.0, "subtotal": 13.0}
    assert cheap(8) == {"rate": 2.0, "distance_amount": 16.0, "subtotal": 26.0}
    assert pricey(3)["subtotal"] == 9.0                      # independent closure
    default = make_rate_calculator(CONFIG["delivery_tiers"], CONFIG["base_charge"])
    assert default(12)["subtotal"] == 29.0


def test_legb_demo_covers_all_four_scopes():
    lines = explain_legb_demo()
    prefixes = [line[:2] for line in lines[:4]]
    assert prefixes == ["L ", "E ", "G ", "B "]
    assert "currency is $" in lines[2] and "is 3" in lines[3]
    assert "local shadow" in lines[4] and "enclosing value" in lines[4]
    assert "a local string" in lines[5] and "is 0" in lines[5]
    assert CONFIG["currency"] == "$"


def test_formatting_helpers():
    assert format_money(36.25) == "$36.25" and format_money(0) == "$0.00"
    assert format_percent(75) == "75.00%" and format_percent(0) == "0.00%"


def run_tests():
    tests = [function for name, function in sorted(globals().items())
             if name.startswith("test_") and callable(function)]
    print("Running tests...\n")
    failures = []
    for test in tests:
        try:
            test()
            print("PASS: " + test.__name__)
        except AssertionError as error:
            failures.append(test.__name__)
            print("FAIL: {} (assertion failed: {!r})".format(test.__name__, error))
    print("\n{}/{} tests passed.".format(len(tests) - len(failures), len(tests)))
    if failures:
        print("Failed: " + ", ".join(failures))
        raise SystemExit(1)
    print("All tests passed.")


if __name__ == "__main__":
    run_tests()