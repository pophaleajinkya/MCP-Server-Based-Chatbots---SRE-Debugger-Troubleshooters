# Valid8 API Reference

All endpoints require **X-API-Key** and **X-Tenant** headers for authentication.
The MCP server handles this automatically — you just call the tool.

---

## Canada (CA) APIs

### 1. Orchestrated Query (OASIS / SKU Validation)
```
POST /ca/api/orchestrated-query
X-API-Key: <api_key>
X-Tenant: ca
Content-Type: application/json

{"sku_id": "6000199554997"}
```

Response includes orchestrated results across: catalog, IMS, MCSE, PNO, search.

---

## Mexico (MX) APIs

### 2. Item Visibility Lookup by UPC
```
POST /mx/item-visibility/lookup-upc
X-API-Key: <api_key>
X-Tenant: mx
Content-Type: application/json

{
  "offerId": "2F1A382F30483E47AD888D0AA01DBDDF",
  "banner": "WM",
  "storeNumber": "2344"
}
```

Returns: `{"offerId": "...", "storeNumber": "...", "success": true, "upc": "00033554661739"}`

### 3. Item Status
```
POST /mx/api/item-status
X-API-Key: <api_key>
X-Tenant: mx
Content-Type: application/json

{
  "banner": "wm-bd",
  "items": ["00085240100638"],
  "format": "table"
}
```

### 4. Order Dashboard Search
```
POST /mx/api/order-dashboard/search
X-API-Key: <api_key>
X-Tenant: mx
Content-Type: application/json

{
  "seller_name": "Bodega Aurrera",
  "time_frame": "30min"
}
```

---

## Common Banners (MX)

| Code | Name |
|------|------|
| `WM` | Walmart Mexico |
| `wm-bd` | Bodega Aurrera |

## Health Check

```
GET /health
```

Returns: `{"status": "healthy"}` (no auth required)
