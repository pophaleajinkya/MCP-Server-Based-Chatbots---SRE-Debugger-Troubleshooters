# Signal API Reference

All endpoints use `accept: application/json` header. No API key is required.
The MCP server handles headers automatically — you just call the tool.

---

## App Inventory

### 1. Get All App Inventory Suggestions
```
GET /api/appInventory/suggestions/all
accept: application/json
```

Returns the complete list of application inventory suggestions.

---

## App Metadata

### 2. Get App Metadata Filters
```
GET /api/appmetadata/filters
accept: application/json
```

Returns the available metadata filter options for applications.

---

## OE Reports

### 3. OE Report — WCNP Certified Data
```
POST /api/oeReport/intl-oe-wcnp-data-certified
accept: application/json
Content-Type: application/json

{
  "tr_product": "All",
  "apm_id": "All"
}
```

Parameters:
- `tr_product`: Product filter. Use "All" for all products.
- `apm_id`: APM ID filter. Use "All" for all APM IDs.

### 4. OE Report — WCNP Not-Certified Data
```
POST /api/oeReport/intl-oe-wcnp-data-not-certified
accept: application/json
Content-Type: application/json

{
  "tr_product": "All",
  "apm_id": "All"
}
```

Parameters:
- `tr_product`: Product filter. Use "All" for all products.
- `apm_id`: APM ID filter. Use "All" for all APM IDs.

---

## Health Check

```
GET /health
```

Returns: `{"status": "healthy"}` (no auth required)
