# Dependency Agent API

API for merging dependencies from multiple sources (database and Walmart topology API).

## Features

- Fetches dependencies from local database (`http://localhost:9099`)
- Fetches dependencies from Walmart topology API
- Merges both sources and returns unique dependencies

## Installation

```bash
# Install dependencies using uv
uv sync
```

## Running the API

```bash
python main.py
```

The API will be available at `http://localhost:8000`

## API Documentation

Once the server is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Usage

### Get Dependencies

**Endpoint:** `POST /dependencies`

**Request Body:**
```json
{
  "appName": "item-read-service-prod2-primary",
  "namespace": "iro-async"
}
```

**Example Request:**
```bash
curl --location 'http://localhost:8013/dependencies' \
  --header 'Content-Type: application/json' \
  --data '{
    "appName": "item-read-service-prod2-primary",
    "namespace": "iro-async"
  }'
```

**Example Response:**
```json
{
  "results": [
    {
      "namespace": "iro-async",
      "appName": "item-read-service-prod2-primary",
      "dependencies": [
        {
          "name": "sct-msce-geo-sourcing::geo-sourcing-service-prod-glass",
          "namespace": "sct-msce-geo-sourcing",
          "app": "geo-sourcing-service-prod-glass",
          "source": "both",
          "type": "k8app",
          "fullName": "sct-msce-geo-sourcing::geo-sourcing-service-prod-glass"
        },
        {
          "name": "product-read-api-prod",
          "namespace": "csis-itemstore",
          "app": "product-read-api-prod",
          "source": "topology",
          "type": "k8app",
          "fullName": "csis-itemstore::product-read-api-prod"
        },
        {
          "name": "meghacache",
          "namespace": null,
          "app": null,
          "source": "topology",
          "type": "meghacache",
          "fullName": null
        }
      ],
      "totalCount": 3,
      "sourceBreakdown": {
        "database_only": 5,
        "topology_only": 18,
        "both": 4,
        "total": 27
      }
    }
  ]
}
```

**Dependency Fields:**
- `name`: Dependency name (can be simple name or namespace::app format)
- `namespace`: Kubernetes namespace of the dependency
- `app`: Application/deployment name of the dependency
- `source`: Where the dependency was found ("database", "topology", or "both")
- `type`: Type of service (k8app, cosmos, meghacache, kafka, etc.)
- `fullName`: Fully qualified name in format namespace::app (if available)

**Source Breakdown:**
- `database_only`: Dependencies found only in the database
- `topology_only`: Dependencies found only in the topology API
- `both`: Dependencies found in both sources
- `total`: Total unique dependencies

**Error Response Example:**
```json
{
  "results": [
    {
      "namespace": "iro-async",
      "appName": "item-read-service-prod2-primary",
      "dependencies": [],
      "totalCount": 0,
      "error": "Failed to fetch dependencies: Connection timeout"
    }
  ]
}
```

## Project Structure

```
dependency_agent/
├── models/
│   ├── __init__.py      # Models package
│   ├── request.py       # Request models
│   └── response.py      # Response models
├── main.py              # Main FastAPI application with all API logic
├── pyproject.toml       # Project configuration
└── README.md            # This file
```

## Configuration

The service connects to:
- **Database API**: `http://localhost:9099/dependencies/wcnp`
- **Topology API**: `https://topology-api.metalake.walmart.com/api/v2/dependency-map`

Topology API credentials are configured in `main.py`.

