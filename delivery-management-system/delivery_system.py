
CONFIG = {
    "currency": "$",
    "base_charge": 5.0,
    "urgent_surcharge": 0.25,
    "delivery_tiers": ((5, 1.0), (10, 1.5), (None, 2.0)),
    "driver_base": 3.0,
    "driver_tiers": ((5, 0.8), (10, 1.2), (None, 1.5)),
    "driver_bonus_percentage": 0.10,
    "bonus_threshold": 150.0,
}

VALID_STATUSES = ("pending", "assigned", "picked_up", "delivered", "failed")
ACTIVE_STATUSES = ("assigned", "picked_up")
TERMINAL_STATUSES = ("delivered", "failed")
VALID_PRIORITIES = ("normal", "urgent")
# pending -> assigned is intentionally absent: it only happens via assignment.
VALID_TRANSITIONS = (
    ("assigned", "picked_up"),
    ("picked_up", "delivered"),
    ("picked_up", "failed"),
)
TASK_FIELDS = ("id", "customer", "zone", "distance", "order_amount", "priority", "status")
DRIVER_FIELDS = ("name", "zone", "available", "rating")


def _success(message, data=None):
    return {"success": True, "message": message, "data": data}


def _failure(message):
    return {"success": False, "message": message, "data": None}


def _is_text(value):
    """True for a non-empty string (after stripping whitespace)."""
    return isinstance(value, str) and value.strip() != ""


def _zone_of(record):
    return record["zone"].strip().upper()


def _priority_of(task):
    return task["priority"].strip().lower()


def _status_of(task):
    return task["status"].strip().lower()


def to_number(value):
    """Convert int/float/numeric string to float.

    Returns (True, number) or (False, None). Rejects bool, NaN, infinity,
    None, lists and non-numeric text.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return False, None
    text = value.strip() if isinstance(value, str) else value
    try:
        number = float(text)
    except (ValueError, OverflowError):
        # The ONLY try/except in the project: converting free text (or a huge
        # int) to float can fail and there is no conditional pre-check for it.
        return False, None
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return False, None
    return True, number


def build_starter_drivers():
    return {
        "D001": {"name": "Ali", "zone": "A", "available": True, "rating": 4.8},
        "D002": {"name": "Ahmed", "zone": "B", "available": True, "rating": 4.5},
        "D003": {"name": "Usman", "zone": "A", "available": False, "rating": 4.9},
        "D004": {"name": "Hamza", "zone": "A", "available": True, "rating": 4.2},
    }


def build_starter_deliveries():
    rows = (
        ("TASK001", "Customer A", "A", 4, 120, "normal"),
        ("TASK002", "Customer B", "B", 12, 80, "urgent"),
        ("TASK003", "Customer C", "A", 7, 200, "normal"),
    )
    return [
        {"id": task_id, "customer": customer, "zone": zone, "distance": distance,
         "order_amount": amount, "priority": priority, "status": "pending", "driver_id": None}
        for task_id, customer, zone, distance, amount, priority in rows
    ]


def calculate_total(*amounts):
    total = 0.0
    for position, amount in enumerate(amounts, start=1):
        ok, number = to_number(amount)
        if not ok or number < 0:
            return _failure("Invalid amount at position {}: {}.".format(position, amount))
        total += number
    return _success("Total calculated.", round(total, 2))


def _total(values):
    """Total of already-validated numbers (thin wrapper over calculate_total)."""
    return calculate_total(*values)["data"]

def make_rate_calculator(tiers, base):
    
    def calculate(distance):
        rate = tiers[-1][1]
        for upper_limit, tier_rate in tiers:  # Local loop variables
            if upper_limit is None or distance <= upper_limit:
                rate = tier_rate
                break
        distance_amount = distance * rate
        return {"rate": rate, "distance_amount": distance_amount,
                "subtotal": base + distance_amount}
    return calculate


def explain_legb_demo():
    
    marker = "enclosing value"  # Enclosing for the inner functions below

    def lookup():
        marker_local = "local value"                      # L
        return [
            "L (Local):     " + marker_local,
            "E (Enclosing): " + marker,                   # found in the outer function
            "G (Global):    currency is " + CONFIG["currency"],
            "B (Built-in):  len([1, 2, 3]) is " + str(len([1, 2, 3])),
        ]

    def shadow_enclosing():
        marker = "local shadow"   # a NEW local; the enclosing `marker` is untouched
        return marker

    def shadow_builtin():
        len = "a local string"    # shadows the built-in only inside this function
        return len

    notes = lookup()
    notes.append("Shadowing: local marker = '{}', enclosing marker still '{}'.".format(
        shadow_enclosing(), marker))
    notes.append("Shadowing: inside shadow_builtin, len = '{}'; outside, len([]) is {}.".format(
        shadow_builtin(), len([])))
    return notes

def _check_options(options, allowed):
    cleaned = {}
    for key in sorted(options):  # sorted -> deterministic error order
        if key not in allowed:
            return _failure("Unknown pricing option: {}.".format(key))
        value = options[key]
        ok, number = to_number(value)
        if isinstance(value, str) or not ok or number < 0:
            return _failure("Invalid value for pricing option {}: {}.".format(key, value))
        cleaned[key] = number
    return _success("Pricing options accepted.", cleaned)


def calculate_delivery_charge(distance, priority, **options):

    ok, km = to_number(distance)
    if not ok or km < 0:
        return _failure("Invalid distance: {}.".format(distance))
    if not isinstance(priority, str) or priority.strip().lower() not in VALID_PRIORITIES:
        return _failure("Invalid priority: {}.".format(priority))
    checked = _check_options(options, ("base_charge", "urgent_surcharge"))
    if not checked["success"]:
        return checked
    settings = checked["data"]
    base = settings.get("base_charge", CONFIG["base_charge"])
    surcharge_rate = settings.get("urgent_surcharge", CONFIG["urgent_surcharge"])

    priced = make_rate_calculator(CONFIG["delivery_tiers"], base)(km)
    is_urgent = priority.strip().lower() == "urgent"
    surcharge = priced["subtotal"] * surcharge_rate if is_urgent else 0.0
    return _success("Delivery charge calculated.", {
        "base": round(base, 2),
        "distance": km,
        "rate": priced["rate"],
        "distance_charge": round(priced["distance_amount"], 2),
        "surcharge": round(surcharge, 2),
        "final_charge": round(priced["subtotal"] + surcharge, 2),
    })


def calculate_driver_earning(distance, order_amount, **options):
    
    ok, km = to_number(distance)
    if not ok or km < 0:
        return _failure("Invalid distance: {}.".format(distance))
    ok, amount = to_number(order_amount)
    if not ok or amount <= 0:
        return _failure("Invalid order amount: {}.".format(order_amount))
    checked = _check_options(
        options, ("driver_base", "driver_bonus_percentage", "bonus_threshold"))
    if not checked["success"]:
        return checked
    settings = checked["data"]
    base = settings.get("driver_base", CONFIG["driver_base"])
    bonus_rate = settings.get("driver_bonus_percentage", CONFIG["driver_bonus_percentage"])
    threshold = settings.get("bonus_threshold", CONFIG["bonus_threshold"])

    priced = make_rate_calculator(CONFIG["driver_tiers"], base)(km)
    bonus = priced["subtotal"] * bonus_rate if amount >= threshold else 0.0
    return _success("Driver earning calculated.", {
        "base": round(base, 2),
        "distance": km,
        "rate": priced["rate"],
        "distance_earning": round(priced["distance_amount"], 2),
        "bonus": round(bonus, 2),
        "total": round(priced["subtotal"] + bonus, 2),
    })

def validate_driver(driver):
    """Check one driver record. Returns a result (data is None)."""
    if not isinstance(driver, dict):
        return _failure("Driver record must be a dictionary.")
    for field in DRIVER_FIELDS:
        if field not in driver:
            return _failure("Missing driver field: {}.".format(field))
    if not _is_text(driver["name"]):
        return _failure("Invalid driver name: {}.".format(driver["name"]))
    if not _is_text(driver["zone"]):
        return _failure("Invalid driver zone: {}.".format(driver["zone"]))
    if not isinstance(driver["available"], bool):
        return _failure("Invalid availability (must be True/False): {}.".format(driver["available"]))
    ok, rating = to_number(driver["rating"])
    if not ok or rating < 0 or rating > 5:
        return _failure("Invalid driver rating: {}.".format(driver["rating"]))
    return _success("Driver is valid.")


def validate_task(task, known_driver_ids=None):
    if not isinstance(task, dict):
        return _failure("Task record must be a dictionary.")
    for field in TASK_FIELDS:
        if field not in task:
            return _failure("Missing task field: {}.".format(field))
    if not _is_text(task["id"]):
        return _failure("Invalid task ID: {}.".format(task["id"]))
    if not _is_text(task["customer"]):
        return _failure("Invalid customer: {}.".format(task["customer"]))
    if not _is_text(task["zone"]):
        return _failure("Invalid zone: {}.".format(task["zone"]))
    ok, distance = to_number(task["distance"])
    if not ok or distance < 0:  # zero is valid
        return _failure("Invalid distance: {}.".format(task["distance"]))
    ok, amount = to_number(task["order_amount"])
    if not ok or amount <= 0:
        return _failure("Invalid order amount: {}.".format(task["order_amount"]))
    if not isinstance(task["priority"], str) or task["priority"].strip().lower() not in VALID_PRIORITIES:
        return _failure("Invalid priority: {}.".format(task["priority"]))
    if not isinstance(task["status"], str) or task["status"].strip().lower() not in VALID_STATUSES:
        return _failure("Invalid status: {}.".format(task["status"]))
    driver_id = task.get("driver_id")
    if driver_id is not None and not _is_text(driver_id):
        return _failure("Invalid driver_id: {}.".format(driver_id))
    if _status_of(task) in ACTIVE_STATUSES:
        if driver_id is None:
            return _failure("Active task {} has no driver_id.".format(task["id"]))
        if known_driver_ids is not None and driver_id not in known_driver_ids:
            return _failure("Active task {} references unknown driver {}.".format(task["id"], driver_id))
    return _success("Task is valid.")


def _load_context(drivers, deliveries, with_figures=False):
    if not isinstance(drivers, dict):
        return _failure("Drivers must be a dictionary.")
    if not isinstance(deliveries, list):
        return _failure("Deliveries must be a list.")

    valid_drivers, rejected_drivers = {}, []
    for driver_id, driver in drivers.items():
        check = validate_driver(driver) if _is_text(driver_id) else _failure(
            "Invalid driver ID: {}.".format(driver_id))
        if check["success"]:
            valid_drivers[driver_id] = driver
        else:
            rejected_drivers.append({"driver_id": driver_id, "reason": check["message"]})

    known_ids = set(valid_drivers)
    tasks, seen_ids, rejected_tasks = [], set(), []
    for task in deliveries:
        check = validate_task(task, known_ids)
        task_id = task.get("id") if isinstance(task, dict) else None
        if not check["success"]:
            rejected_tasks.append({"task_id": task_id, "reason": check["message"]})
        elif task_id in seen_ids:
            rejected_tasks.append({"task_id": task_id, "reason": "Duplicate task ID: {}.".format(task_id)})
        else:
            seen_ids.add(task_id)
            tasks.append(task)

    figures = {}
    if with_figures:
        for task in tasks:
            if _status_of(task) == "delivered":
                charge = calculate_delivery_charge(task["distance"], task["priority"])
                earning = calculate_driver_earning(task["distance"], task["order_amount"])
                figures[task["id"]] = {"charge": charge["data"]["final_charge"],
                                       "earning": earning["data"]["total"]}

    return _success("Data loaded.", {
        "drivers": valid_drivers,
        "rejected_drivers": rejected_drivers,
        "tasks": tasks,
        "task_index": {task["id"]: task for task in tasks},
        # A driver with an assigned/picked_up task is busy even if the flag is wrong.
        "busy_driver_ids": {task["driver_id"] for task in tasks if _status_of(task) in ACTIVE_STATUSES},
        "rejected_tasks": rejected_tasks,
        "figures": figures,
    })


def _lookup(mapping, key):
    """dict.get that tolerates unhashable keys (lists, dicts) from bad input."""
    return mapping.get(key) if isinstance(key, str) else None


def _task_missing_message(context, task_id):
    for item in context["rejected_tasks"]:
        if item["task_id"] == task_id and task_id is not None:
            return "Task {} has invalid data: {}".format(task_id, item["reason"])
    return "Task {} not found.".format(task_id)


def _driver_missing_message(context, driver_id):
    for item in context["rejected_drivers"]:
        if item["driver_id"] == driver_id:
            return "Driver {} has invalid data: {}".format(driver_id, item["reason"])
    return "Driver {} not found.".format(driver_id)


def _terminal_message(task_id, status):
    if status == "delivered":
        return "Task {} has already been delivered.".format(task_id)
    return "Task {} has already failed.".format(task_id)


def get_eligible_drivers(drivers, zone, busy_driver_ids=()):
    wanted = zone.strip().upper()
    return [driver_id for driver_id, driver in drivers.items()
            if driver["available"] and driver_id not in busy_driver_ids
            and _zone_of(driver) == wanted]


def pick_best_driver(drivers, driver_ids):
    if not driver_ids:
        return None
    return min(driver_ids, key=lambda driver_id: (-float(drivers[driver_id]["rating"]), driver_id))


def _check_task_is_assignable(task):
    status = _status_of(task)
    if status in TERMINAL_STATUSES:
        return _failure(_terminal_message(task["id"], status))
    if status != "pending" or task.get("driver_id") is not None:
        return _failure("Task {} has already been assigned.".format(task["id"]))
    return None


def _assign(task, driver, driver_id):
    """The single place where an assignment changes state."""
    driver["available"] = False
    task["driver_id"] = driver_id
    task["status"] = "assigned"
    return _success("Task {} assigned to driver {}.".format(task["id"], driver_id),
                    {"task_id": task["id"], "driver_id": driver_id})


def assign_driver(drivers, deliveries, task_id, driver_id):
    
    loaded = _load_context(drivers, deliveries)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    task = _lookup(context["task_index"], task_id)
    if task is None:
        return _failure(_task_missing_message(context, task_id))
    blocked = _check_task_is_assignable(task)
    if blocked:
        return blocked
    driver = _lookup(context["drivers"], driver_id)
    if driver is None:
        return _failure(_driver_missing_message(context, driver_id))
    if not driver["available"] or driver_id in context["busy_driver_ids"]:
        return _failure("Driver {} is currently busy.".format(driver_id))
    if _zone_of(driver) != _zone_of(task):
        return _failure("Driver {} is in zone {}, but task {} requires zone {}.".format(
            driver_id, _zone_of(driver), task["id"], _zone_of(task)))
    return _assign(task, driver, driver_id)


def allocate_driver(drivers, deliveries, task_id):
    """Automatically pick the best eligible driver for one task."""
    loaded = _load_context(drivers, deliveries)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    task = _lookup(context["task_index"], task_id)
    if task is None:
        return _failure(_task_missing_message(context, task_id))
    blocked = _check_task_is_assignable(task)
    if blocked:
        return blocked
    eligible = get_eligible_drivers(context["drivers"], task["zone"], context["busy_driver_ids"])
    best = pick_best_driver(context["drivers"], eligible)
    if best is None:
        return _failure("No available driver exists in zone {}.".format(_zone_of(task)))
    return _assign(task, context["drivers"][best], best)


def _build_driver_queues(drivers, busy_driver_ids):
    candidates = [(driver_id, driver) for driver_id, driver in drivers.items()
                  if driver["available"] and driver_id not in busy_driver_ids]
    worst_first = sorted(candidates,
                         key=lambda item: (-float(item[1]["rating"]), item[0]),
                         reverse=True)
    queues = {}
    for driver_id, driver in worst_first:
        queues.setdefault(_zone_of(driver), []).append(driver_id)
    return queues


def allocate_pending_tasks(drivers, deliveries):
    loaded = _load_context(drivers, deliveries)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    pending = sorted(
        [task for task in context["tasks"]
         if _status_of(task) == "pending" and task.get("driver_id") is None],
        key=lambda task: (0 if _priority_of(task) == "urgent" else 1, task["id"]),
    )
    queues = _build_driver_queues(context["drivers"], context["busy_driver_ids"])
    assigned, unassigned = [], []
    for task in pending:
        queue = queues.get(_zone_of(task))
        if queue:
            driver_id = queue.pop()
            _assign(task, context["drivers"][driver_id], driver_id)
            assigned.append({"task_id": task["id"], "driver_id": driver_id})
        else:
            unassigned.append({"task_id": task["id"],
                               "reason": "No available driver exists in zone {}.".format(_zone_of(task))})
    return _success(
        "Batch allocation completed: {} assigned, {} unassigned.".format(len(assigned), len(unassigned)),
        {"assigned": assigned, "unassigned": unassigned,
         "rejected_tasks": context["rejected_tasks"],
         "rejected_drivers": context["rejected_drivers"]})

def update_delivery_status(drivers, deliveries, task_id, new_status):
    """Move a task along assigned -> picked_up -> delivered/failed.

    pending -> assigned is only possible through assign_driver/allocate_driver.
    Reaching delivered or failed releases the driver (never earlier).
    data = {task_id, old_status, new_status, driver_released}
    """
    loaded = _load_context(drivers, deliveries)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    task = _lookup(context["task_index"], task_id)
    if task is None:
        return _failure(_task_missing_message(context, task_id))
    if not isinstance(new_status, str) or new_status.strip().lower() not in VALID_STATUSES:
        return _failure("Invalid status: {}.".format(new_status))
    new = new_status.strip().lower()
    old = _status_of(task)
    if old in TERMINAL_STATUSES:
        return _failure(_terminal_message(task["id"], old))
    if old == "pending" and new == "assigned":
        return _failure("Use assign_driver or allocate_driver to move task {} from pending to assigned.".format(task["id"]))
    if (old, new) not in VALID_TRANSITIONS:
        return _failure("Invalid status transition: {} -> {}.".format(old, new))

    task["status"] = new
    released = None
    if new in TERMINAL_STATUSES:
        driver = _lookup(context["drivers"], task.get("driver_id"))
        if driver is not None:
            driver["available"] = True
            released = task["driver_id"]
    return _success("Task {} moved from {} to {}.".format(task["id"], old, new),
                    {"task_id": task["id"], "old_status": old, "new_status": new,
                     "driver_released": released})


def task_delivery_charge(task):
    """Delivery charge breakdown for a task record (validates the task first)."""
    check = validate_task(task)
    if not check["success"]:
        return check
    return calculate_delivery_charge(task["distance"], task["priority"])


def task_driver_earning(task):
    """Driver earning breakdown for a task record. Failed tasks earn zero."""
    check = validate_task(task)
    if not check["success"]:
        return check
    if _status_of(task) == "failed":
        _, km = to_number(task["distance"])
        return _success("Failed deliveries earn zero.", {
            "base": 0.0, "distance": km, "rate": 0.0,
            "distance_earning": 0.0, "bonus": 0.0, "total": 0.0})
    return calculate_driver_earning(task["distance"], task["order_amount"])


def _new_zone_row(zone):
    return {"zone": zone, "total_tasks": 0, "delivered_tasks": 0,
            "driver_count": 0, "delivered_revenue": 0.0}


def _build_report_stats(context):

    drivers, tasks, figures = context["drivers"], context["tasks"], context["figures"]

    driver_rows = {
        driver_id: {"driver_id": driver_id, "name": driver["name"], "zone": _zone_of(driver),
                    "total_assigned": 0, "delivered": 0, "failed": 0,
                    "total_distance": 0.0, "total_earnings": 0.0}
        for driver_id, driver in drivers.items()
    }

    # set: unique zones from BOTH drivers and tasks
    unique_zones = {_zone_of(driver) for driver in drivers.values()} | \
                   {_zone_of(task) for task in tasks}
    zone_rows = {zone: _new_zone_row(zone) for zone in unique_zones}
    for driver in drivers.values():
        zone_rows[_zone_of(driver)]["driver_count"] += 1

    for task in tasks:
        zone_row = zone_rows[_zone_of(task)]
        driver_row = driver_rows.get(task.get("driver_id"))  # None for unassigned tasks
        zone_row["total_tasks"] += 1
        if driver_row is not None:
            driver_row["total_assigned"] += 1
        status = _status_of(task)
        if status == "delivered":
            figure = figures[task["id"]]
            zone_row["delivered_tasks"] += 1
            zone_row["delivered_revenue"] += figure["charge"]
            if driver_row is not None:
                driver_row["delivered"] += 1
                driver_row["total_distance"] += float(task["distance"])
                driver_row["total_earnings"] += figure["earning"]
        elif status == "failed" and driver_row is not None:
            driver_row["failed"] += 1

    for row in driver_rows.values():
        row["total_distance"] = round(row["total_distance"], 2)
        row["total_earnings"] = round(row["total_earnings"], 2)
        row["completion_rate"] = (round(row["delivered"] / row["total_assigned"] * 100, 2)
                                  if row["total_assigned"] else 0.0)
    for row in zone_rows.values():
        row["delivered_revenue"] = round(row["delivered_revenue"], 2)

    return {
        "drivers": sorted(driver_rows.values(),
                          key=lambda row: (-row["total_earnings"], row["driver_id"])),
        "zones": sorted(zone_rows.values(),
                        key=lambda row: (-row["delivered_revenue"], row["zone"])),
    }


def _unassigned_tasks(context):
    """Pending tasks without a driver, each with the reason it is waiting."""
    free_zones = {_zone_of(driver) for driver_id, driver in context["drivers"].items()
                  if driver["available"] and driver_id not in context["busy_driver_ids"]}
    waiting = sorted((task for task in context["tasks"]
                      if _status_of(task) == "pending" and task.get("driver_id") is None),
                     key=lambda task: task["id"])
    return [{"task_id": task["id"],
             "reason": ("Awaiting allocation: a driver is available in zone {}.".format(_zone_of(task))
                        if _zone_of(task) in free_zones
                        else "No available driver exists in zone {}.".format(_zone_of(task)))}
            for task in waiting]


def driver_performance_report(drivers, deliveries):

    loaded = _load_context(drivers, deliveries, with_figures=True)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    return _success("Driver performance report generated.", {
        "drivers": _build_report_stats(context)["drivers"],
        "rejected_tasks": context["rejected_tasks"],
        "rejected_drivers": context["rejected_drivers"]})


def zone_report(drivers, deliveries):
    """Per-zone task counts and delivered revenue (delivery charges)."""
    loaded = _load_context(drivers, deliveries, with_figures=True)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    return _success("Zone report generated.", {
        "zones": _build_report_stats(context)["zones"],
        "rejected_tasks": context["rejected_tasks"],
        "rejected_drivers": context["rejected_drivers"]})


def additional_reports(drivers, deliveries):
    """Business reports: zones, per-zone counts/revenue, order stats, driver
    availability, urgent and unassigned tasks. Works on empty data."""
    loaded = _load_context(drivers, deliveries, with_figures=True)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    tasks = context["tasks"]
    zone_rows = _build_report_stats(context)["zones"]
    longest = min(tasks, key=lambda task: (-float(task["distance"]), task["id"])) if tasks else None
    highest = min(tasks, key=lambda task: (-float(task["order_amount"]), task["id"])) if tasks else None
    return _success("Additional reports generated.", {
        "unique_zones": sorted(row["zone"] for row in zone_rows),
        "tasks_per_zone": {row["zone"]: row["total_tasks"] for row in zone_rows},
        "revenue_per_zone": {row["zone"]: row["delivered_revenue"] for row in zone_rows},
        "average_order_amount": (round(_total(float(task["order_amount"]) for task in tasks) / len(tasks), 2)
                                 if tasks else 0.0),
        "longest_delivery": ({"task_id": longest["id"], "distance": float(longest["distance"])}
                             if longest else None),
        "highest_value_order": ({"task_id": highest["id"], "order_amount": float(highest["order_amount"])}
                                if highest else None),
        "available_drivers": sorted(driver_id for driver_id, driver in context["drivers"].items()
                                    if driver["available"]),
        "busy_drivers": sorted(driver_id for driver_id, driver in context["drivers"].items()
                               if not driver["available"]),
        "urgent_deliveries": sorted(task["id"] for task in tasks if _priority_of(task) == "urgent"),
        "unassigned_tasks": _unassigned_tasks(context),
        "rejected_tasks": context["rejected_tasks"],
        "rejected_drivers": context["rejected_drivers"],
    })


def dashboard_data(drivers, deliveries):

    loaded = _load_context(drivers, deliveries, with_figures=True)
    if not loaded["success"]:
        return loaded
    context = loaded["data"]
    tasks, figures = context["tasks"], context["figures"]
    stats = _build_report_stats(context)

    status_counts = {status: 0 for status in VALID_STATUSES}
    for task in tasks:
        status_counts[_status_of(task)] += 1

    deliverers = [row for row in stats["drivers"] if row["delivered"] > 0]
    top = min(deliverers, key=lambda row: (-row["delivered"], -row["total_earnings"], row["driver_id"])) \
        if deliverers else None
    best_zone = stats["zones"][0] if stats["zones"] else None  # zones are already ranked

    return _success("Dashboard generated.", {
        "total_tasks": len(tasks),
        "status_counts": status_counts,
        "total_order_value": _total(float(task["order_amount"]) for task in tasks),
        "total_delivery_charges": _total(item["charge"] for item in figures.values()),
        "total_driver_earnings": _total(item["earning"] for item in figures.values()),
        "top_driver": {"driver_id": top["driver_id"], "name": top["name"]} if top else None,
        "highest_revenue_zone": (best_zone["zone"] if best_zone and best_zone["delivered_revenue"] > 0
                                 else "N/A"),
        "average_delivery_distance": (round(_total(float(task["distance"]) for task in tasks) / len(tasks), 2)
                                      if tasks else 0.0),
        "unassigned_tasks": [item["task_id"] for item in _unassigned_tasks(context)],
        "rejected_tasks": context["rejected_tasks"],
        "rejected_drivers": context["rejected_drivers"],
    })

def format_money(amount):
    return "{}{:.2f}".format(CONFIG["currency"], amount)


def format_percent(value):
    return "{:.2f}%".format(value)


def _join(items):
    return ", ".join(items) if items else "None"


def render_charge_breakdown(task_id, charge):
    return "{}: base {} + distance {} ({:g} km x {}/km) + surcharge {} = {}".format(
        task_id, format_money(charge["base"]), format_money(charge["distance_charge"]),
        charge["distance"], format_money(charge["rate"]), format_money(charge["surcharge"]),
        format_money(charge["final_charge"]))


def render_earning_breakdown(task_id, earning):
    return "{}: base {} + distance {} ({:g} km x {}/km) + bonus {} = {}".format(
        task_id, format_money(earning["base"]), format_money(earning["distance_earning"]),
        earning["distance"], format_money(earning["rate"]), format_money(earning["bonus"]),
        format_money(earning["total"]))


def render_driver_report(rows):
    layout = "{:<6}{:<8}{:<6}{:>9}{:>10}{:>7}{:>11}{:>11}{:>12}"
    lines = [layout.format("ID", "Name", "Zone", "Assigned", "Delivered", "Failed",
                           "Distance", "Earnings", "Completion")]
    lines.extend(layout.format(
        row["driver_id"], row["name"], row["zone"], row["total_assigned"], row["delivered"],
        row["failed"], "{:.2f} km".format(row["total_distance"]),
        format_money(row["total_earnings"]), format_percent(row["completion_rate"])) for row in rows)
    return "\n".join(lines)


def render_zone_report(rows):
    layout = "{:<6}{:>7}{:>11}{:>9}{:>12}"
    lines = [layout.format("Zone", "Tasks", "Delivered", "Drivers", "Revenue")]
    lines.extend(layout.format(row["zone"], row["total_tasks"], row["delivered_tasks"],
                               row["driver_count"], format_money(row["delivered_revenue"]))
                 for row in rows)
    return "\n".join(lines)


def render_additional_reports(data):
    longest, highest = data["longest_delivery"], data["highest_value_order"]
    lines = [
        "Unique zones: " + _join(data["unique_zones"]),
        "Tasks per zone: " + _join(["{}={}".format(z, n) for z, n in sorted(data["tasks_per_zone"].items())]),
        "Revenue per zone: " + _join(["{}={}".format(z, format_money(v))
                                      for z, v in sorted(data["revenue_per_zone"].items())]),
        "Average order amount: " + format_money(data["average_order_amount"]),
        "Longest delivery: " + ("{} ({:.2f} km)".format(longest["task_id"], longest["distance"])
                                if longest else "N/A"),
        "Highest-value order: " + ("{} ({})".format(highest["task_id"], format_money(highest["order_amount"]))
                                   if highest else "N/A"),
        "Available drivers: " + _join(data["available_drivers"]),
        "Busy drivers: " + _join(data["busy_drivers"]),
        "Urgent deliveries: " + _join(data["urgent_deliveries"]),
        "Tasks that could not be assigned:",
    ]
    lines.extend("- {}: {}".format(item["task_id"], item["reason"]) for item in data["unassigned_tasks"])
    if not data["unassigned_tasks"]:
        lines.append("- None")
    return "\n".join(lines)


def render_dashboard(data):
    counts = data["status_counts"]
    top = data["top_driver"]
    lines = [
        "========== DELIVERY DASHBOARD ==========",
        "Total Tasks: {}".format(data["total_tasks"]),
        "Pending: {}".format(counts["pending"]),
        "Assigned: {}".format(counts["assigned"]),
        "Picked Up: {}".format(counts["picked_up"]),
        "Delivered: {}".format(counts["delivered"]),
        "Failed: {}".format(counts["failed"]),
        "Total Order Value: {}".format(format_money(data["total_order_value"])),
        "Total Delivery Charges: {}".format(format_money(data["total_delivery_charges"])),
        "Total Driver Earnings: {}".format(format_money(data["total_driver_earnings"])),
        "Top Driver: {}".format("{} ({})".format(top["driver_id"], top["name"]) if top else "N/A"),
        "Highest Revenue Zone: {}".format(data["highest_revenue_zone"]),
        "Average Delivery Distance: {:.2f} km".format(data["average_delivery_distance"]),
        "Unassigned Tasks:",
    ]
    lines.extend("- " + task_id for task_id in data["unassigned_tasks"] or ["None"])
    lines.append("========================================")
    return "\n".join(lines)


def print_result(operation):
    print(("OK:       " if operation["success"] else "REJECTED: ") + operation["message"])


def _print_section(title):
    print("\n=== {} ===".format(title))


def main():
    drivers = build_starter_drivers()
    deliveries = build_starter_deliveries()

    _print_section("DRIVER ALLOCATION")
    batch = allocate_pending_tasks(drivers, deliveries)
    print_result(batch)
    for item in batch["data"]["assigned"]:
        driver = drivers[item["driver_id"]]
        print("  {} ({}) -> {}".format(driver["name"], item["driver_id"], item["task_id"]))
    for step in (("TASK001", "picked_up"), ("TASK001", "delivered"),
                 ("TASK003", "picked_up"), ("TASK003", "failed")):
        print_result(update_delivery_status(drivers, deliveries, *step))
    print("  Drivers available again: D001={}, D004={}".format(
        drivers["D001"]["available"], drivers["D004"]["available"]))
    deliveries.append({"id": "TASK004", "customer": "Customer D", "zone": "C", "distance": 0,
                       "order_amount": 50, "priority": "normal", "status": "pending", "driver_id": None})
    extra = allocate_pending_tasks(drivers, deliveries)
    print_result(extra)
    for item in extra["data"]["unassigned"]:
        print("  {} stays unassigned: {}".format(item["task_id"], item["reason"]))

    _print_section("REJECTED OPERATIONS")
    for operation in (
        assign_driver(drivers, deliveries, "TASK999", "D001"),
        assign_driver(drivers, deliveries, "TASK004", "D002"),
        update_delivery_status(drivers, deliveries, "TASK002", "delivered"),
        allocate_driver(drivers, deliveries, "TASK001"),
        calculate_delivery_charge(-5, "normal"),
        calculate_delivery_charge(3, "super_urgent"),
    ):
        print_result(operation)

    _print_section("DELIVERY CHARGES")
    for task in deliveries:
        print(render_charge_breakdown(task["id"], task_delivery_charge(task)["data"]))

    _print_section("DRIVER EARNINGS")
    for task in deliveries:
        print(render_earning_breakdown(task["id"], task_driver_earning(task)["data"]))

    _print_section("DRIVER PERFORMANCE")
    print(render_driver_report(driver_performance_report(drivers, deliveries)["data"]["drivers"]))

    _print_section("ZONE REPORT")
    print(render_zone_report(zone_report(drivers, deliveries)["data"]["zones"]))

    _print_section("ADDITIONAL REPORTS")
    print(render_additional_reports(additional_reports(drivers, deliveries)["data"]))

    _print_section("DELIVERY DASHBOARD")
    print(render_dashboard(dashboard_data(drivers, deliveries)["data"]))

    _print_section("LEGB DEMO")
    print("\n".join(explain_legb_demo()))


if __name__ == "__main__":
    main()