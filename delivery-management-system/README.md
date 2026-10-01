# Delivery & Driver Allocation Management System

Pure Python, in-memory delivery system built only from Python fundamentals. It validates deliveries and drivers, allocates drivers automatically, prices deliveries, calculates driver earnings, enforces a status workflow, and produces performance, zone and dashboard reports.

No classes, no files or databases, no frameworks, no third-party packages, no imports in the implementation.

## Files

| File | Purpose |
|---|---|
| `delivery_system.py` | All business logic, report/render functions and a `main()` demo |
| `test_delivery_system.py` | Assert-based tests with a small PASS/FAIL runner |
| `README.md` | This document |

## How to run

```text
python delivery_system.py          # demo: allocation, workflow, reports, dashboard
python test_delivery_system.py     # all tests (use python3 on Linux/macOS)
```

## Architecture

Business functions never print. They return a uniform result dictionary:

```python
{"success": True,  "message": "Task TASK001 assigned to driver D001.", "data": {...}}
{"success": False, "message": "Driver D002 is currently busy.",        "data": None}
```

Only `render_*`, `print_result` and `main` format text or print.

Every public operation receives `drivers` (dict keyed by driver ID) and `deliveries` (list of dicts) as parameters, validates them **once** in `_load_context`, then works on that validated view. The view holds the original dict objects, so assignments and status changes reach the caller's data.

| Layer | Functions |
|---|---|
| Validation | `to_number`, `validate_task`, `validate_driver`, `_load_context` |
| Pricing and earnings | `calculate_delivery_charge`, `calculate_driver_earning`, `make_rate_calculator`, `task_delivery_charge`, `task_driver_earning` |
| Totals | `calculate_total` (`*args`) |
| Allocation | `get_eligible_drivers`, `pick_best_driver`, `assign_driver`, `allocate_driver`, `allocate_pending_tasks` |
| Workflow | `update_delivery_status` |
| Reports | `driver_performance_report`, `zone_report`, `additional_reports`, `dashboard_data` (all fed by `_build_report_stats`) |
| Presentation | `format_money`, `format_percent`, `render_charge_breakdown`, `render_earning_breakdown`, `render_driver_report`, `render_zone_report`, `render_additional_reports`, `render_dashboard`, `print_result`, `main` |
| Scope demo | `explain_legb_demo`, `make_rate_calculator` |

## Data structures

- **Drivers**: dict `driver_id -> {"name", "zone", "available", "rating"}`.
- **Deliveries**: list of dicts `{"id", "customer", "zone", "distance", "order_amount", "priority", "status", "driver_id"}`. `driver_id` is optional on input and treated as `None` when missing.
- **Tuples** hold fixed data: status lists, valid transitions, rate tiers.
- **Sets** hold unique zones, seen task IDs, known driver IDs, busy driver IDs and zones with a free driver.
- `build_starter_drivers()` and `build_starter_deliveries()` return fresh structures on every call, so no mutable business data lives at module level. `CONFIG` is read-only by convention: no function modifies it and the `global` keyword is never used.

## Validation rules

| Field | Rule |
|---|---|
| Task `id`, `customer` | non-empty text |
| `zone` | non-empty text; compared after `strip().upper()` |
| `distance` | int, float or numeric string; **0 is valid**; negative, bool, NaN, infinity and non-numeric text are rejected |
| `order_amount` | same formats, but must be **greater than 0** |
| `priority` | `normal` or `urgent` after `strip().lower()` |
| `status` | `pending`, `assigned`, `picked_up`, `delivered`, `failed` |
| Active task (`assigned`/`picked_up`) | must have a `driver_id` of a known, valid driver |
| Driver `available` | strictly `True` or `False` |
| Driver `rating` | number from 0 to 5 inclusive |

Invalid or duplicate records are skipped and listed in `rejected_tasks` / `rejected_drivers` of the result. They never stop valid records from being processed. The first valid occurrence of a task ID is used; later duplicates are rejected. Operations that name a rejected task or driver say why, e.g. `Task TASK001 has invalid data: Invalid distance: -3.`

## Pricing

Brackets are **flat**: the whole distance is priced at the rate of the bracket it falls in. Boundaries use `<=`, so 5.5 km uses the 6-10 km rate.

| Distance | Delivery charge rate | Driver earning rate |
|---|---|---|
| up to 5 km | $1.00/km | $0.80/km |
| above 5, up to 10 km | $1.50/km | $1.20/km |
| above 10 km | $2.00/km | $1.50/km |

**Delivery charge**: `subtotal = $5.00 + distance * rate`. Urgent tasks add 25% of the subtotal. The result contains `base`, `distance`, `rate`, `distance_charge`, `surcharge`, `final_charge`.

- 4 km normal: 5 + 4 x 1.00 = **$9.00**
- 12 km urgent: (5 + 12 x 2.00) x 1.25 = **$36.25**
- 0 km: base only, $5.00 ($6.25 if urgent)

**Driver earning**: `subtotal = $3.00 + distance * rate`. If `order_amount >= $150`, add 10% of the subtotal. The result contains `base`, `distance`, `rate`, `distance_earning`, `bonus`, `total`.

- 4 km, $120 order: 3 + 4 x 0.80 = **$6.20**
- 7 km, $200 order: (3 + 7 x 1.20) x 1.10 = **$12.54**
- 0 km, $150 order: 3 x 1.10 = **$3.30**

Calculations use unrounded values; each returned amount is rounded to 2 decimals. Failed tasks earn $0 (`task_driver_earning`). Customer charge and driver earning are separate calculations.

## Driver allocation

A driver is eligible when the driver record is valid, `available` is `True`, the driver has no active task, and the zone matches the task zone. A task can be allocated only while it is `pending` with no `driver_id`.

- **Selection**: highest rating wins.
- **Tie-break**: equal ratings choose the lexicographically smallest driver ID (`D001` beats `D004`). Implemented once in `pick_best_driver` with `min(..., key=lambda ...)` on `(-rating, driver_id)`.
- **On success**: `driver["available"] = False`, `task["driver_id"] = id`, `task["status"] = "assigned"` (single place: `_assign`).
- **On failure**: nothing changes and the message explains why, e.g. `No available driver exists in zone C.`
- **Batch** (`allocate_pending_tasks`): urgent tasks first, then by task ID. Drivers are ranked once per zone, so the cost is O(T log T + D log D). The result is identical to calling `allocate_driver` repeatedly in that order (covered by a test).
- **Direct** (`assign_driver`): rejects unknown task/driver, delivered/failed/already-assigned tasks, busy drivers and drivers from another zone.
- A driver holds at most one active task. A driver whose flag says available but who still has an `assigned`/`picked_up` task is treated as busy.

## Status workflow

```text
pending -> assigned -> picked_up -> delivered
                           |
                           +-----> failed
```

Valid transitions are only `assigned -> picked_up`, `picked_up -> delivered` and `picked_up -> failed`. `pending -> assigned` happens only through `assign_driver` / `allocate_driver`; `update_delivery_status` refuses it and says so. Everything else is rejected, including same-status updates, backward moves and any move out of `delivered` or `failed` (`Task TASK001 has already been delivered.`).

When a task becomes `delivered` or `failed`, its driver becomes available again. Never earlier.

## Reports and dashboard

All report numbers come from `_build_report_stats`, which aggregates drivers and tasks in linear passes and is the only place that ranks results:

- driver rows: highest total earnings first, then lowest driver ID
- zone rows: highest delivered revenue first, then alphabetical

**Driver report** (every valid driver, including drivers with no tasks): total assigned = tasks carrying that driver ID in any status; delivered; failed; total distance and total earnings from **delivered tasks only**; completion rate = delivered / assigned x 100, or 0.00% when nothing is assigned.

**Zone report**: zones come from a set built from driver zones and task zones. Each row has task count, delivered count, driver count and delivered delivery-charge revenue.

**Additional reports** (`additional_reports`): unique zones, tasks per zone, revenue per zone, average order amount, longest delivery, highest-value order, available drivers, busy drivers (flag is `False`), urgent deliveries, and unassigned tasks with a reason. Ties for longest delivery and highest-value order choose the lexicographically smallest task ID.

**Dashboard definitions** (these metrics are project decisions, not part of the original assignment text):

| Metric | Definition |
|---|---|
| Total Tasks / status counts | valid tasks only |
| Total Order Value | order amounts of all valid tasks |
| Total Delivery Charges | final charges of **delivered** tasks |
| Total Driver Earnings | earnings of **delivered** tasks |
| Top Driver | most delivered tasks, then higher total earnings, then lowest driver ID; `N/A` if nobody delivered |
| Highest Revenue Zone | top of the revenue ranking, alphabetical on ties; `N/A` if no delivered revenue |
| Average Delivery Distance | mean distance over all valid tasks; 0.00 if none |
| Unassigned Tasks | pending tasks without a driver ID; `- None` when empty |

Empty drivers and empty deliveries are supported by every report (zeros, `N/A`, empty lists).

## Required Python features, and where they are used

- **`*args`**: `calculate_total(*amounts)` totals any number of values, rejecting bool, NaN, infinity, text and negatives. `_total` calls it for dashboard totals, average order amount and average distance. (Per-driver and per-zone running sums inside `_build_report_stats` use `+=` and are rounded at the end.)
- **`**kwargs`**: `calculate_delivery_charge(distance, priority, **options)` accepts `base_charge` and `urgent_surcharge` (a fraction such as 0.25). `calculate_driver_earning(distance, order_amount, **options)` accepts `driver_base`, `driver_bonus_percentage` and `bonus_threshold`. Values must be real numbers (not bool, not text) and >= 0. An unknown key fails with its name. Overrides apply to that call only; `CONFIG` is never changed.
- **lambda**: sort/min keys for driver choice (`pick_best_driver`), per-zone driver queues, batch task order, driver and zone ranking, top driver, longest delivery and highest-value order.
- **Comprehensions**: starter data, `get_eligible_drivers`, task index, busy driver set, driver/zone row dicts, report dictionaries.
- **Set**: `unique_zones` in `_build_report_stats` (drivers' zones united with tasks' zones), plus `seen_ids`, `known_ids`, `busy_driver_ids`, `free_zones`.

## LEGB

- **Local**: variables inside any function, e.g. `rate` and the loop variables inside `calculate` in `make_rate_calculator`.
- **Enclosing**: `make_rate_calculator(tiers, base)` returns `calculate(distance)`, which reads `tiers` and `base` from the outer function. Both pricing functions use it, so the closure is real code, not a demo.
- **Global**: `CONFIG`. `calculate_delivery_charge` and `calculate_driver_earning` read it (`CONFIG["delivery_tiers"]`, `CONFIG["base_charge"]`, ...) without `global` and without modifying it.
- **Built-in**: `len`, `min`, `sorted`, `round`, `float`, `isinstance`.
- **Shadowing**: `explain_legb_demo()` returns lines showing a local `marker` hiding the enclosing `marker`, and a local `len` hiding the built-in only inside one inner function.

## Error handling

Invalid business data returns a failure result; it never raises. Typical messages:

```text
Task TASK999 not found.
Driver D999 not found.
Driver D002 is currently busy.
No available driver exists in zone C.
Invalid priority: super_urgent.
Invalid distance: -5.
Invalid status transition: assigned -> delivered.
Task TASK001 has already been assigned.
Task TASK001 has already been delivered.
Unknown pricing option: bogus.
```

Wrong container types (`None` instead of a dict or list, unhashable IDs) are rejected with a message too. The only `try`/`except` in the implementation is in `to_number`, catching `ValueError` and `OverflowError` when converting text or a huge int to `float`. (The test runner also catches `AssertionError` so it can print PASS/FAIL for every test.)

## Edge cases and the tests that cover them

| Edge case | Test |
|---|---|
| Invalid driver ID / invalid task ID | `test_assign_driver_rejections`, `test_invalid_task_is_reported_by_id` |
| Zero distance | `test_delivery_charge_boundaries`, `test_driver_earning_distance_brackets` |
| Negative distance | `test_delivery_charge_invalid_input`, `test_validate_task_rejections` |
| Invalid order amount | `test_driver_earning_kwargs_and_invalid_input`, `test_validate_task_rejections` |
| Invalid priority / status | `test_delivery_charge_invalid_input`, `test_update_status_invalid_input` |
| No driver in zone | `test_no_driver_in_zone` |
| Already-assigned task | `test_already_assigned_task_rejected` |
| Busy driver | `test_busy_driver_rejected`, `test_single_active_task_rule` |
| Equal ratings | `test_tie_break_lowest_driver_id`, `test_top_driver_tie_breaks` |
| Invalid transition | `test_every_invalid_transition_is_rejected_and_changes_nothing` |
| Delivered / failed task processed again | `test_delivered_and_failed_tasks_cannot_be_reprocessed` |
| Empty drivers / empty deliveries | `test_empty_drivers_and_empty_deliveries`, `test_reports_on_completely_empty_data` |
| Bad types, duplicates, broken records | `test_wrong_container_types_never_crash`, `test_duplicate_and_invalid_records_are_skipped`, `test_invalid_driver_record_is_reported_and_never_chosen` |

## Test results

Command: `python3 test_delivery_system.py`. Output observed when this README was written:

```text
Running tests...

PASS: test_additional_reports
PASS: test_allocation_picks_highest_rating
PASS: test_allocation_respects_zone_and_availability
PASS: test_already_assigned_task_rejected
PASS: test_assign_driver_rejections
PASS: test_batch_equals_repeated_single_allocation
PASS: test_batch_urgent_first_and_multiple_allocations
PASS: test_busy_driver_rejected
PASS: test_calculate_total_args
PASS: test_closure_remembers_enclosing_values
PASS: test_dashboard_revenue_zone_tie_is_alphabetical
PASS: test_dashboard_values_and_exact_layout
PASS: test_delivered_and_failed_tasks_cannot_be_reprocessed
PASS: test_delivery_charge_boundaries
PASS: test_delivery_charge_breakdown
PASS: test_delivery_charge_invalid_input
PASS: test_delivery_charge_kwargs
PASS: test_driver_earning_bonus_threshold
PASS: test_driver_earning_distance_brackets
PASS: test_driver_earning_kwargs_and_invalid_input
PASS: test_driver_report_totals_zero_task_driver_and_completion
PASS: test_duplicate_and_invalid_records_are_skipped
PASS: test_empty_drivers_and_empty_deliveries
PASS: test_every_invalid_transition_is_rejected_and_changes_nothing
PASS: test_failed_operations_do_not_mutate_data
PASS: test_failed_path_releases_driver
PASS: test_failed_task_earns_zero
PASS: test_formatting_helpers
PASS: test_fresh_starter_data
PASS: test_full_workflow_delivered_releases_driver
PASS: test_invalid_driver_record_is_reported_and_never_chosen
PASS: test_invalid_task_is_reported_by_id
PASS: test_legb_demo_covers_all_four_scopes
PASS: test_no_driver_in_zone
PASS: test_numeric_string_tasks_work_end_to_end
PASS: test_reports_on_completely_empty_data
PASS: test_reports_share_one_ranking_and_set_based_zones
PASS: test_single_active_task_rule
PASS: test_tie_break_lowest_driver_id
PASS: test_top_driver_tie_breaks
PASS: test_unassigned_reason_when_driver_is_available
PASS: test_update_status_invalid_input
PASS: test_validate_driver
PASS: test_validate_task_accepts_and_normalises
PASS: test_validate_task_active_needs_known_driver
PASS: test_validate_task_rejections
PASS: test_wrong_container_types_never_crash
PASS: test_zone_report_multiple_zones_ranked_by_revenue

48/48 tests passed.
All tests passed.
```

## Example output

Command: `python3 delivery_system.py`. The demo allocates the starter data, delivers TASK001, fails TASK003, adds an unservable zone C task, shows rejected operations, then prints every report.

```text
=== DRIVER ALLOCATION ===
OK:       Batch allocation completed: 3 assigned, 0 unassigned.
  Ahmed (D002) -> TASK002
  Ali (D001) -> TASK001
  Hamza (D004) -> TASK003
OK:       Task TASK001 moved from assigned to picked_up.
OK:       Task TASK001 moved from picked_up to delivered.
OK:       Task TASK003 moved from assigned to picked_up.
OK:       Task TASK003 moved from picked_up to failed.
  Drivers available again: D001=True, D004=True
OK:       Batch allocation completed: 0 assigned, 1 unassigned.
  TASK004 stays unassigned: No available driver exists in zone C.

=== REJECTED OPERATIONS ===
REJECTED: Task TASK999 not found.
REJECTED: Driver D002 is currently busy.
REJECTED: Invalid status transition: assigned -> delivered.
REJECTED: Task TASK001 has already been delivered.
REJECTED: Invalid distance: -5.
REJECTED: Invalid priority: super_urgent.

=== DELIVERY CHARGES ===
TASK001: base $5.00 + distance $4.00 (4 km x $1.00/km) + surcharge $0.00 = $9.00
TASK002: base $5.00 + distance $24.00 (12 km x $2.00/km) + surcharge $7.25 = $36.25
TASK003: base $5.00 + distance $10.50 (7 km x $1.50/km) + surcharge $0.00 = $15.50
TASK004: base $5.00 + distance $0.00 (0 km x $1.00/km) + surcharge $0.00 = $5.00

=== DRIVER EARNINGS ===
TASK001: base $3.00 + distance $3.20 (4 km x $0.80/km) + bonus $0.00 = $6.20
TASK002: base $3.00 + distance $18.00 (12 km x $1.50/km) + bonus $0.00 = $21.00
TASK003: base $0.00 + distance $0.00 (7 km x $0.00/km) + bonus $0.00 = $0.00
TASK004: base $3.00 + distance $0.00 (0 km x $0.80/km) + bonus $0.00 = $3.00

=== DRIVER PERFORMANCE ===
ID    Name    Zone   Assigned Delivered Failed   Distance   Earnings  Completion
D001  Ali     A             1         1      0    4.00 km      $6.20     100.00%
D002  Ahmed   B             1         0      0    0.00 km      $0.00       0.00%
D003  Usman   A             0         0      0    0.00 km      $0.00       0.00%
D004  Hamza   A             1         0      1    0.00 km      $0.00       0.00%

=== ZONE REPORT ===
Zone    Tasks  Delivered  Drivers     Revenue
A           2          1        3       $9.00
B           1          0        1       $0.00
C           1          0        0       $0.00

=== ADDITIONAL REPORTS ===
Unique zones: A, B, C
Tasks per zone: A=2, B=1, C=1
Revenue per zone: A=$9.00, B=$0.00, C=$0.00
Average order amount: $112.50
Longest delivery: TASK002 (12.00 km)
Highest-value order: TASK003 ($200.00)
Available drivers: D001, D004
Busy drivers: D002, D003
Urgent deliveries: TASK002
Tasks that could not be assigned:
- TASK004: No available driver exists in zone C.

=== DELIVERY DASHBOARD ===
========== DELIVERY DASHBOARD ==========
Total Tasks: 4
Pending: 1
Assigned: 1
Picked Up: 0
Delivered: 1
Failed: 1
Total Order Value: $450.00
Total Delivery Charges: $9.00
Total Driver Earnings: $6.20
Top Driver: D001 (Ali)
Highest Revenue Zone: A
Average Delivery Distance: 5.75 km
Unassigned Tasks:
- TASK004
========================================

=== LEGB DEMO ===
L (Local):     local value
E (Enclosing): enclosing value
G (Global):    currency is $
B (Built-in):  len([1, 2, 3]) is 3
Shadowing: local marker = 'local shadow', enclosing marker still 'enclosing value'.
Shadowing: inside shadow_builtin, len = 'a local string'; outside, len([]) is 0.
```

## Assumptions and decisions

These details were not fixed by the assignment text; the project chose them and keeps them consistent:

- Flat-bracket pricing (not progressive slabs).
- Zero distance is valid; order amount must be greater than 0.
- Equal ratings: lowest driver ID. Batch order: urgent first, then task ID.
- Driver distance, earnings and zone revenue count delivered tasks only; failed tasks earn $0.
- Top Driver, Highest Revenue Zone and the other dashboard definitions above.
- Average Delivery Distance and Total Order Value include every valid task regardless of status.
- Task and driver IDs are matched exactly (case-sensitive); zones are normalised to upper case only for comparison.
- A pending task that already carries a `driver_id` is neither allocatable nor listed as unassigned.
- `calculate_total` rejects negative values, so it cannot total refunds or discounts.

## Limitations

- Data lives only in memory; nothing is saved between runs.
- Every public call validates all drivers and tasks again (O(T + D)), which is fine for this scale but not a persistent index.
- Money uses floats rounded to 2 decimals, not exact decimals.
- Performance numbers (about 0.25 s to batch-allocate 50,000 tasks on the machine used during development) were measured once and are not guaranteed.