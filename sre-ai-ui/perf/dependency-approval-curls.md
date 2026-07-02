# Dependency Approval Flow — Complete Guide

**Base URL:** `http://localhost:9099`

---

## Overview

An approval workflow for adding or removing dependencies between applications.
Instead of directly writing to the `dependency` table, every request goes through a `dependency_approval` table where it must be reviewed before taking effect.

---

## How It Works

```
                 ┌──────────────────────────────────────────────────────┐
                 │               dependency_approval table               │
                 └──────────────────────────────────────────────────────┘

 [User: john.doe]
      │
      │  POST /dependency-approvals
      │  { applicationId, dependencyId, action: "ADD", requestedBy: "john.doe" }
      ▼
 ┌───────────────────┐
 │  status: PENDING  │  ◄── dependency table: NO CHANGE
 │  requestedBy: john│
 │  approvedBy: null │
 └───────────────────┘
      │
      ├──────────────────────────────────────────────────┐
      │                                                  │
      │  PUT /dependency-approvals/{id}/approve          │  PUT /dependency-approvals/{id}/reject
      │  { approvedBy: "jane.smith" }                    │  { approvedBy: "jane.smith" }
      ▼                                                  ▼
 ┌───────────────────┐                         ┌───────────────────┐
 │ status: APPROVED  │──► dependency table:    │ status: REJECTED  │◄── dependency table:
 │ requestedBy: john │    ROW INSERTED/DELETED │ requestedBy: john │    NO CHANGE
 │ approvedBy: jane  │    (source = "user")    │ approvedBy: jane  │
 └───────────────────┘                         └───────────────────┘
```

---

## ADD Dependency Flow

```
POST /dependency-approvals  →  { action: "ADD" }
        │
        ▼  status: PENDING
        │
PUT /dependency-approvals/{id}/approve  →  { approvedBy: "jane.smith" }
        │
        ▼  status: APPROVED  ──►  dependency table: ROW INSERTED  (source = "user")
```

---

## DELETE Dependency Flow

```
POST /dependency-approvals  →  { action: "DELETE" }
        │
        ▼  status: PENDING
        │
PUT /dependency-approvals/{id}/approve  →  { approvedBy: "jane.smith" }
        │
        ▼  status: APPROVED  ──►  dependency table: ROW DELETED
```

---

## Auto-Reject Flow (previously rejected request re-submitted)

```
POST /dependency-approvals  →  same applicationId + dependencyId + action as a REJECTED record
        │
        ▼  status: REJECTED instantly  (approvedBy = "system")
             reason = "Auto-rejected: previous request was rejected by <user> with reason: <reason>"
             dependency table: NO CHANGE
```

---

## Business Rules

| Rule | Behaviour |
|------|-----------|
| Duplicate PENDING guard | If a `PENDING` request already exists for the same `(applicationId, dependencyId)`, the new request errors |
| Auto-reject | If the same `(applicationId, dependencyId, action)` was previously `REJECTED`, the new request is instantly auto-rejected by system |
| Can't act on non-PENDING | Trying to approve/reject an already `APPROVED` or `REJECTED` record throws an error |
| `requestedBy` is immutable | Set once at creation from request body, never overwritten — always shows the original requester |
| `approvedBy` is only set at action time | Null until approve/reject is called |
| `source = "user"` on approval | When a dependency is created via the approval flow, its `dependency_sources` record is `"user"` |

---

## Table: `dependency_approval`

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGINT | Auto-generated primary key |
| `application_id` | BIGINT | The application making the request |
| `dependency_id` | BIGINT | The dependency application being added/removed |
| `action` | VARCHAR | `ADD` or `DELETE` |
| `status` | VARCHAR | `PENDING`, `APPROVED`, `REJECTED` |
| `reason` | TEXT | Reason from requester or reviewer |
| `requested_by` | VARCHAR | Username of the requester (from request body, never changes) |
| `approved_by` | VARCHAR | Username of the approver (from request body at action time) |
| `approved_at` | TIMESTAMP | When approval/rejection happened |
| `creation_timestamp` | TIMESTAMP | Audit — record creation time |
| `modification_timestamp` | TIMESTAMP | Audit — last update time |
| `creation_user` | VARCHAR | Audit — same as `requested_by` |
| `modification_user` | VARCHAR | Audit — last user who modified |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/dependency-approvals` | Submit ADD or DELETE request |
| PUT | `/dependency-approvals/{id}/approve` | Approve a PENDING request |
| PUT | `/dependency-approvals/{id}/reject` | Reject a PENDING request |
| GET | `/dependency-approvals` | Get all approval records |
| GET | `/dependency-approvals/status/{status}` | Filter by PENDING / APPROVED / REJECTED |
| GET | `/dependency-approvals/application/{applicationId}` | All approvals for an application |
| GET | `/dependency-approvals/{id}` | Get single approval record by ID |

---

## cURL Test Guide

---

## 1. Submit an ADD request

```bash
curl -X POST http://localhost:9099/dependency-approvals \
  -H "Content-Type: application/json" \
  -d '{
    "applicationId": 101,
    "dependencyId": 202,
    "action": "ADD",
    "requestedBy": "john.doe",
    "reason": "Need this service for payment processing"
  }'
```

**Expected `201 Created`:**
```json
{
  "status": 201,
  "message": "Dependency approval request submitted successfully",
  "data": {
    "id": 1,
    "applicationId": 101,
    "applicationName": "checkout-service",
    "dependencyId": 202,
    "dependencyName": "payment-service",
    "action": "ADD",
    "status": "PENDING",
    "reason": "Need this service for payment processing",
    "requestedBy": "john.doe",
    "approvedBy": null,
    "approvedAt": null,
    "createdAt": "2026-03-26T10:00:00.000+00:00",
    "updatedAt": "2026-03-26T10:00:00.000+00:00"
  }
}
```

> ✅ Only `dependency_approval` table is updated. The `dependency` table is **not touched yet**.

---

## 2. Submit a DELETE request

```bash
curl -X POST http://localhost:9099/dependency-approvals \
  -H "Content-Type: application/json" \
  -d '{
    "applicationId": 101,
    "dependencyId": 202,
    "action": "DELETE",
    "requestedBy": "john.doe",
    "reason": "Removing stale dependency"
  }'
```

**Expected `201 Created`:**
```json
{
  "status": 201,
  "message": "Dependency approval request submitted successfully",
  "data": {
    "id": 2,
    "applicationId": 101,
    "applicationName": "checkout-service",
    "dependencyId": 202,
    "dependencyName": "payment-service",
    "action": "DELETE",
    "status": "PENDING",
    "reason": "Removing stale dependency",
    "requestedBy": "john.doe",
    "approvedBy": null,
    "approvedAt": null,
    "createdAt": "2026-03-26T10:00:00.000+00:00",
    "updatedAt": "2026-03-26T10:00:00.000+00:00"
  }
}
```

---

## 3. Approve a request

> Replace `1` with the actual `id` from step 1.

```bash
curl -X PUT http://localhost:9099/dependency-approvals/1/approve \
  -H "Content-Type: application/json" \
  -d '{
    "approvedBy": "jane.smith",
    "reason": "Verified — dependency is valid and required"
  }'
```

**Expected `200 OK`:**
```json
{
  "status": 200,
  "message": "Dependency request approved successfully",
  "data": {
    "id": 1,
    "applicationId": 101,
    "applicationName": "checkout-service",
    "dependencyId": 202,
    "dependencyName": "payment-service",
    "action": "ADD",
    "status": "APPROVED",
    "reason": "Verified — dependency is valid and required",
    "requestedBy": "john.doe",
    "approvedBy": "jane.smith",
    "approvedAt": "2026-03-26T10:30:00.000+00:00",
    "createdAt": "2026-03-26T10:00:00.000+00:00",
    "updatedAt": "2026-03-26T10:30:00.000+00:00"
  }
}
```

> ✅ `dependency_approval` row → `status = APPROVED`
> ✅ A new row is inserted into the `dependency` table with `source = "user"`

---

## 4. Reject a request

> Replace `2` with the actual `id` from step 2.

```bash
curl -X PUT http://localhost:9099/dependency-approvals/2/reject \
  -H "Content-Type: application/json" \
  -d '{
    "approvedBy": "jane.smith",
    "reason": "Duplicate dependency — already covered by another service"
  }'
```

**Expected `200 OK`:**
```json
{
  "status": 200,
  "message": "Dependency request rejected successfully",
  "data": {
    "id": 2,
    "applicationId": 101,
    "applicationName": "checkout-service",
    "dependencyId": 202,
    "dependencyName": "payment-service",
    "action": "DELETE",
    "status": "REJECTED",
    "reason": "Duplicate dependency — already covered by another service",
    "requestedBy": "john.doe",
    "approvedBy": "jane.smith",
    "approvedAt": "2026-03-26T10:35:00.000+00:00",
    "createdAt": "2026-03-26T10:00:00.000+00:00",
    "updatedAt": "2026-03-26T10:35:00.000+00:00"
  }
}
```

> ✅ `dependency_approval` row → `status = REJECTED`
> ✅ The `dependency` table is **not changed**

---

## 5. Auto-reject — re-submit a previously rejected request

> Submit the same `applicationId + dependencyId + action` that was already REJECTED in step 4.

```bash
curl -X POST http://localhost:9099/dependency-approvals \
  -H "Content-Type: application/json" \
  -d '{
    "applicationId": 101,
    "dependencyId": 202,
    "action": "DELETE",
    "requestedBy": "john.doe",
    "reason": "Trying again"
  }'
```

**Expected `201 Created` (auto-rejected instantly by system):**
```json
{
  "status": 201,
  "message": "Dependency approval request submitted successfully",
  "data": {
    "id": 3,
    "applicationId": 101,
    "applicationName": "checkout-service",
    "dependencyId": 202,
    "dependencyName": "payment-service",
    "action": "DELETE",
    "status": "REJECTED",
    "reason": "Auto-rejected: a previous request was rejected by jane.smith with reason: \"Duplicate dependency — already covered by another service\"",
    "requestedBy": "john.doe",
    "approvedBy": "system",
    "approvedAt": "2026-03-26T10:40:00.000+00:00"
  }
}
```

---

## 6. Duplicate PENDING guard

> Submit the same request twice without approving or rejecting in between.

```bash
# First call — goes PENDING
curl -X POST http://localhost:9099/dependency-approvals \
  -H "Content-Type: application/json" \
  -d '{
    "applicationId": 101,
    "dependencyId": 205,
    "action": "ADD",
    "requestedBy": "john.doe",
    "reason": "First attempt"
  }'

# Second call immediately after — should error
curl -X POST http://localhost:9099/dependency-approvals \
  -H "Content-Type: application/json" \
  -d '{
    "applicationId": 101,
    "dependencyId": 205,
    "action": "ADD",
    "requestedBy": "john.doe",
    "reason": "Duplicate attempt"
  }'
```

**Expected error on second call:**
```json
{
  "message": "A PENDING approval request already exists for applicationId: 101 and dependencyId: 205"
}
```

---

## 7. Act on an already-decided record (guard)

> Try to approve a record that is already APPROVED.

```bash
curl -X PUT http://localhost:9099/dependency-approvals/1/approve \
  -H "Content-Type: application/json" \
  -d '{
    "approvedBy": "jane.smith",
    "reason": "Trying to approve again"
  }'
```

**Expected error:**
```json
{
  "message": "Approval request with id: 1 is already APPROVED and cannot be acted upon."
}
```

---

## 8. Get all approval records

```bash
curl -X GET http://localhost:9099/dependency-approvals
```

---

## 9. Filter by status

```bash
# PENDING
curl -X GET http://localhost:9099/dependency-approvals/status/PENDING

# APPROVED
curl -X GET http://localhost:9099/dependency-approvals/status/APPROVED

# REJECTED
curl -X GET http://localhost:9099/dependency-approvals/status/REJECTED
```

---

## 10. Get all approvals for a specific application

```bash
curl -X GET http://localhost:9099/dependency-approvals/application/101
```

---

## 11. Get a single approval record by ID

```bash
curl -X GET http://localhost:9099/dependency-approvals/1
```

---

## Quick Reference

| # | Method | Endpoint | Purpose |
|---|--------|----------|---------|
| 1 | POST | `/dependency-approvals` | Submit ADD request → PENDING |
| 2 | POST | `/dependency-approvals` | Submit DELETE request → PENDING |
| 3 | PUT | `/dependency-approvals/{id}/approve` | Approve → APPROVED + dependency row inserted/deleted |
| 4 | PUT | `/dependency-approvals/{id}/reject` | Reject → REJECTED + dependency table unchanged |
| 5 | POST | `/dependency-approvals` | Re-submit rejected → auto-rejected by system |
| 6 | POST | `/dependency-approvals` | Duplicate PENDING → error |
| 7 | PUT | `/dependency-approvals/{id}/approve` | Act on decided record → error |
| 8 | GET | `/dependency-approvals` | Get all records |
| 9 | GET | `/dependency-approvals/status/{status}` | Filter by PENDING / APPROVED / REJECTED |
| 10 | GET | `/dependency-approvals/application/{applicationId}` | All approvals for an application |
| 11 | GET | `/dependency-approvals/{id}` | Single approval by ID |

