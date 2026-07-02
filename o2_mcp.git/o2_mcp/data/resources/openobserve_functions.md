# OpenObserve Custom DataFusion Functions

This document provides a comprehensive reference for all custom User-Defined Functions (UDFs) and User-Defined Aggregate Functions (UDAFs) available in OpenObserve's Apache DataFusion query engine.

## Table of Contents

- [Scalar Functions (UDFs)](#scalar-functions-udfs)
  - [Array Functions](#array-functions)
  - [String Matching Functions](#string-matching-functions)
  - [Date/Time Functions](#datetime-functions)
  - [JSON Functions](#json-functions)
  - [Encryption Functions](#encryption-functions-enterprise)
  - [Other Functions](#other-functions)
- [Aggregate Functions (UDAFs)](#aggregate-functions-udafs)

---

## Scalar Functions (UDFs)

### Array Functions

#### `arr_descending(array_field)`

**Description:** Sorts an array in descending order.

**Signature:**
```sql
arr_descending(array_field: STRING) -> STRING
```

**Parameters:**
- `array_field`: JSON string representation of an array (e.g., `'[3, 1, 4, 1, 5]'`)

**Returns:** JSON string of the sorted array in descending order

**Example:**
```sql
SELECT arr_descending('[3, 1, 4, 1, 5]')
-- Returns: '[5, 4, 3, 1, 1]'

SELECT arr_descending('["zebra", "apple", "banana"]')
-- Returns: '["zebra", "banana", "apple"]'
```

**Notes:**
- Supports numbers (integers and floats), strings, and booleans
- Returns NULL for invalid JSON or non-array inputs
- Empty arrays return NULL

---

#### `arrcount(array_field)`

**Description:** Returns the count of elements in an array.

**Signature:**
```sql
arrcount(array_field: STRING) -> UINT64
```

**Parameters:**
- `array_field`: JSON string representation of an array

**Returns:** Number of elements in the array (0 for invalid input)

**Example:**
```sql
SELECT arrcount('[1, 2, 3, 4, 5]')
-- Returns: 5

SELECT arrcount('["a", "b", "c"]')
-- Returns: 3

SELECT arrcount('not an array')
-- Returns: 0
```

---

#### `arrindex(array_field, start_index, end_index)`

**Description:** Extracts a slice of elements from an array using start and end indices (inclusive).

**Signature:**
```sql
arrindex(array_field: STRING, start: INT64, end: INT64) -> STRING
```

**Parameters:**
- `array_field`: JSON string representation of an array
- `start`: Starting index (0-based, inclusive)
- `end`: Ending index (inclusive)

**Returns:** JSON string array containing elements from start to end index

**Example:**
```sql
SELECT arrindex('[10, 20, 30, 40, 50]', 1, 3)
-- Returns: '[20, 30, 40]'

SELECT arrindex('["a", "b", "c", "d"]', 0, 1)
-- Returns: '["a", "b"]'

-- If end index exceeds array length, returns up to last element
SELECT arrindex('[1, 2, 3]', 1, 10)
-- Returns: '[2, 3]'
```

**Notes:**
- Both indices are inclusive
- Returns empty array `[]` if start index is out of bounds
- If end index exceeds array length, returns up to the last element

---

#### `arrjoin(array_field, delimiter)`

**Description:** Joins array elements into a single string using a delimiter.

**Signature:**
```sql
arrjoin(array_field: STRING, delimiter: STRING) -> STRING
```

**Parameters:**
- `array_field`: JSON string representation of an array
- `delimiter`: String to use as separator between elements

**Returns:** Concatenated string of all array elements

**Example:**
```sql
SELECT arrjoin('["hello", "world"]', ', ')
-- Returns: 'hello, world'

SELECT arrjoin('[1, 2, 3, 4]', '-')
-- Returns: '1-2-3-4'

SELECT arrjoin('[true, false, true]', '|')
-- Returns: 'true|false|true'
```

---

#### `arrsort(array_field)`

**Description:** Sorts an array in ascending order.

**Signature:**
```sql
arrsort(array_field: STRING) -> STRING
```

**Parameters:**
- `array_field`: JSON string representation of an array

**Returns:** JSON string of the sorted array in ascending order

**Example:**
```sql
SELECT arrsort('[3, 1, 4, 1, 5]')
-- Returns: '[1, 1, 3, 4, 5]'

SELECT arrsort('["zebra", "apple", "banana"]')
-- Returns: '["apple", "banana", "zebra"]'

SELECT arrsort('[true, false, true]')
-- Returns: '[false, true, true]'
```

**Notes:**
- Supports numbers (integers and floats), strings, and booleans
- Returns NULL for invalid JSON or non-array inputs
- Empty arrays return NULL

---

#### `arrzip(array1, array2, delimiter)`

**Description:** Zips two arrays together, combining corresponding elements with a delimiter.

**Signature:**
```sql
arrzip(array1: STRING, array2: STRING, delimiter: STRING) -> STRING
```

**Parameters:**
- `array1`: JSON string representation of the first array
- `array2`: JSON string representation of the second array
- `delimiter`: String to use as separator between paired elements

**Returns:** JSON string array of zipped elements

**Example:**
```sql
SELECT arrzip('["a", "b", "c"]', '[1, 2, 3]', ':')
-- Returns: '["a:1", "b:2", "c:3"]'

SELECT arrzip('[12, 345, 23]', '[1.9, 34.5, 2.6]', ',')
-- Returns: '["12,1.9", "345,34.5", "23,2.6"]'
```

**Notes:**
- Zips elements pair-wise from both arrays
- Only zips up to the length of the shorter array
- Returns NULL if either array is empty or invalid

---

#### `cast_to_arr(field)`

**Description:** Converts a JSON array string to a native DataFusion List array type.

**Signature:**
```sql
cast_to_arr(field: STRING) -> LIST<STRING>
```

**Parameters:**
- `field`: JSON string representation of an array

**Returns:** DataFusion List array of strings

**Example:**
```sql
SELECT cast_to_arr('[1, 2, 3, 4]')
-- Returns: [1, 2, 3, 4] (as List<String>)

SELECT cast_to_arr('["hello", "world"]')
-- Returns: [hello, world]
```

**Notes:**
- Filters out empty string elements
- Returns NULL for invalid JSON or non-array inputs
- Useful for converting JSON arrays to native DataFusion array types

---

#### `to_array_string(array)`

**Description:** Converts a DataFusion List array to a JSON string representation.

**Signature:**
```sql
to_array_string(array: LIST<STRING>) -> STRING
```

**Parameters:**
- `array`: DataFusion List array

**Returns:** JSON string representation of the array

**Example:**
```sql
SELECT to_array_string(ARRAY['a', 'b', 'c'])
-- Returns: '["a","b","c"]'
```

**Notes:**
- Inverse operation of `cast_to_arr`
- Returns NULL for NULL input

---

#### `string_to_array_v2(string, delimiter)`

**Description:** Splits a string into an array using each character in the delimiter string as a separator.

**Signature:**
```sql
string_to_array_v2(string: STRING, delimiter: STRING) -> LIST<STRING>
```

**Parameters:**
- `string`: String to split
- `delimiter`: String where each character is treated as a separator

**Returns:** DataFusion List array of string elements

**Example:**
```sql
SELECT string_to_array_v2('a,b;c', ',;')
-- Returns: [a, b, c]

SELECT string_to_array_v2('hello-world_test', '-_')
-- Returns: [hello, world, test]
```

**Notes:**
- Each character in the delimiter is treated as an individual separator
- Empty delimiter returns the entire string as a single element
- Different from standard `string_to_array` which treats the delimiter as a whole string

---

### String Matching Functions

#### `str_match(field, pattern)`

**Aliases:** `match_field(field, pattern)`

**Description:** Checks if a field contains the exact pattern (case-sensitive). Always use `str_match` instead of `match_field` in queries to keep it consistent.

**Signature:**
```sql
str_match(field: STRING, pattern: STRING) -> BOOLEAN
```

**Parameters:**
- `field`: Field or column to search in
- `pattern`: Exact string pattern to search for

**Returns:** TRUE if the pattern is found, FALSE otherwise

**Example:**
```sql
SELECT * FROM logs WHERE str_match(message, 'error')
-- Returns rows where message contains 'error'

SELECT * FROM logs WHERE str_match(status, '404')
-- Returns rows where status contains '404'
```

---

#### `str_match_ignore_case(field, pattern)`

**Aliases:** `match_field_ignore_case(field, pattern)`

**Description:** Checks if a field contains the pattern (case-insensitive). Always use `str_match_ignore_case` instead of `match_field_ignore_case` to keep it consistent.

**Signature:**
```sql
str_match_ignore_case(field: STRING, pattern: STRING) -> BOOLEAN
```

**Parameters:**
- `field`: Field or column to search in
- `pattern`: String pattern to search for (case-insensitive)

**Returns:** TRUE if the pattern is found, FALSE otherwise

**Example:**
```sql
SELECT * FROM logs WHERE str_match_ignore_case(message, 'ERROR')
-- Matches 'error', 'Error', 'ERROR', etc.
```

---

#### `match_all(pattern)`

**Description:** Searches for a pattern across all fields in a record.

**Signature:**
```sql
match_all(pattern: STRING) -> BOOLEAN
```

**Parameters:**
- `pattern`: String pattern to search for across all fields

**Returns:** TRUE if pattern is found in any field

**Example:**
```sql
SELECT * FROM logs WHERE match_all('exception')
-- Returns rows where 'exception' appears in any field
```

**Notes:**
- Searches across all string fields in the record
- Does not support SQL with multiple streams

---

#### `fuzzy_match(field, pattern, distance)`

**Description:** Performs fuzzy string matching using Levenshtein distance.

**Signature:**
```sql
fuzzy_match(field: STRING, pattern: STRING, distance: INT64) -> BOOLEAN
```

**Parameters:**
- `field`: Field or column to search in
- `pattern`: String pattern to match
- `distance`: Maximum allowed Levenshtein distance (edit distance)

**Returns:** TRUE if any token in the field matches the pattern within the specified distance

**Example:**
```sql
SELECT * FROM logs WHERE fuzzy_match(message, 'data', 1)
-- Matches 'data', 'date', 'datt', etc. (1 character difference)

SELECT * FROM logs WHERE fuzzy_match(log, 'error', 2)
-- Matches 'error', 'eror', 'errrr', etc. (up to 2 edits away)
```

**Notes:**
- Uses token-based matching (tokenizes the field first)
- Useful for handling typos and minor variations

---

#### `fuzzy_match_all(pattern, distance)`

**Description:** Performs fuzzy matching across all fields.

**Signature:**
```sql
fuzzy_match_all(pattern: STRING, distance: INT64) -> BOOLEAN
```

**Parameters:**
- `pattern`: String pattern to match
- `distance`: Maximum allowed Levenshtein distance

**Returns:** TRUE if pattern matches any field within the distance

**Example:**
```sql
SELECT * FROM logs WHERE fuzzy_match_all('error', 1)
-- Fuzzy matches 'error' (or similar) across all fields
```

---

#### `re_match(field, pattern)`

**Description:** Checks if a field matches a regular expression pattern.

**Signature:**
```sql
re_match(field: STRING, pattern: STRING) -> BOOLEAN
```

**Parameters:**
- `field`: Field or column to match against
- `pattern`: Regular expression pattern

**Returns:** TRUE if the field matches the regex pattern

**Example:**
```sql
SELECT * FROM logs WHERE re_match(ip_address, '^192\.168\.')
-- Matches IP addresses starting with 192.168.

SELECT * FROM logs WHERE re_match(email, '.*@example\.com$')
-- Matches emails ending with @example.com
```

---

#### `re_not_match(field, pattern)`

**Description:** Checks if a field does NOT match a regular expression pattern.

**Signature:**
```sql
re_not_match(field: STRING, pattern: STRING) -> BOOLEAN
```

**Parameters:**
- `field`: Field or column to match against
- `pattern`: Regular expression pattern

**Returns:** TRUE if the field does NOT match the regex pattern

**Example:**
```sql
SELECT * FROM logs WHERE re_not_match(status, '^[45]')
-- Returns rows where status doesn't start with 4 or 5
```

---

#### `re_matches(field, pattern)`

**Description:** Extracts all substrings that match a regular expression pattern.

**Signature:**
```sql
re_matches(field: STRING, pattern: STRING) -> LIST<STRING>
```

**Parameters:**
- `field`: Field or column to extract matches from
- `pattern`: Regular expression pattern

**Returns:** List of matched substrings, or empty list if no matches

**Example:**
```sql
SELECT re_matches(log, '\d{3}-\d{3}-\d{4}')
-- Extracts phone numbers like '123-456-7890'

SELECT re_matches(text, '[A-Z][a-z]+')
-- Extracts capitalized words
```

**Notes:**
- Returns a List array, not a JSON string
- Returns empty list if no matches found
- Returns NULL if input is NULL

---

### Date/Time Functions

#### `cast_to_timestamp(value)`

**Description:** Converts various formats to a microsecond timestamp (Int64).

**Signature:**
```sql
cast_to_timestamp(value: STRING|TIMESTAMP|INT64) -> INT64
```

**Parameters:**
- `value`: Date/time value in various formats:
  - ISO 8601 strings: `'2025-01-01T00:00:00.000Z'`
  - Timestamps with timezone: `'2025-01-01T00:00:00+08:00'`
  - Numeric timestamps (microseconds)
  - DataFusion TIMESTAMP types
  - Expressions like `NOW()`, `NOW() - INTERVAL '1 hour'`

**Returns:** Timestamp as Int64 (microseconds since epoch)

**Example:**
```sql
SELECT * FROM logs WHERE time <= cast_to_timestamp(NOW())

SELECT * FROM logs WHERE time > cast_to_timestamp('2025-01-01T00:00:00.000Z')

SELECT * FROM logs WHERE time > cast_to_timestamp(NOW() - INTERVAL '1 hour')

SELECT * FROM logs WHERE time > cast_to_timestamp(1740398708294000)
```

**Notes:**
- Primary function for timestamp conversions in OpenObserve
- Handles multiple timestamp formats and timezones
- Always returns microseconds since Unix epoch

---

#### `date_format(timestamp, format, timezone)`

**Description:** Formats a timestamp according to a format string and timezone.

**Signature:**
```sql
date_format(timestamp: INT64, format: STRING, timezone: STRING) -> STRING
```

**Parameters:**
- `timestamp`: Timestamp in microseconds since epoch
- `format`: strftime-style format string (e.g., `'%Y-%m-%d'`, `'%H:%M:%S'`)
- `timezone`: Timezone offset (e.g., `'UTC'`, `'+08:00'`, `'-05:00'`, `''` for UTC)

**Returns:** Formatted date/time string

**Example:**
```sql
SELECT date_format(time, '%Y-%m-%d', 'UTC')
-- Returns: '2025-01-01'

SELECT date_format(time, '%H:%M:%S', '+08:00')
-- Returns: '08:00:00' (8 hours ahead of UTC)

SELECT date_format(time, '%Y-%m-%dT%H:%M:%S', '-05:00')
-- Returns: '2025-01-01T19:00:00' (5 hours behind UTC)
```

**Notes:**
- Uses chrono's format strings
- Empty string for timezone defaults to UTC

---

#### `time_range(timestamp, start, end)`

**Description:** Checks if a timestamp falls within a specified time range.

**Signature:**
```sql
time_range(timestamp: INT64, start: STRING, end: STRING) -> BOOLEAN
```

**Parameters:**
- `timestamp`: Timestamp to check (microseconds since epoch)
- `start`: Start of range (ISO 8601 timestamp string)
- `end`: End of range (ISO 8601 timestamp string)

**Returns:** TRUE if timestamp is within [start, end), FALSE otherwise

**Example:**
```sql
SELECT * FROM logs 
WHERE time_range(time, '2025-01-01T00:00:00Z', '2025-01-02T00:00:00Z')
-- Returns logs from Jan 1, 2025 (00:00 inclusive to Jan 2, 00:00 exclusive)
```

**Notes:**
- Range is inclusive of start, exclusive of end [start, end)
- Returns NULL if timestamp parsing fails

---

#### `histogram(timestamp, interval)`

**Description:** Rounds timestamp to histogram bucket boundaries.

**Signature:**
```sql
histogram(timestamp: TIMESTAMP, interval: STRING) -> TIMESTAMP
```

**Parameters:**
- `timestamp`: Timestamp field
- `interval`: Bucket interval (e.g., `'1 minute'`, `'5 minutes'`, `'1 hour'`)

**Returns:** Timestamp rounded to the bucket boundary

**Example:**
```sql
SELECT histogram(time, '5 minutes') as time_bucket, COUNT(*) 
FROM logs 
GROUP BY time_bucket
ORDER BY time_bucket
-- Groups logs into 5-minute buckets
```

**Notes:**
- Used for time-series aggregations
- Implementation is specialized for OpenObserve's histogram queries

---

### JSON Functions

#### `spath(field, path)`

**Description:** Navigates a JSON object using dot-notation path and returns the value.

**Signature:**
```sql
spath(field: STRING, path: STRING) -> STRING
```

**Parameters:**
- `field`: JSON string
- `path`: Dot-notation path (e.g., `'user.name'`, `'data.items[0].value'`)

**Returns:** Stringified JSON value at the specified path, or NULL if not found

**Example:**
```sql
SELECT spath('{"user":{"name":"John","age":30}}', 'user.name')
-- Returns: 'John'

SELECT spath('{"data":{"items":[{"id":1}]}}', 'data.items')
-- Returns: '[{"id":1}]'
```

**Notes:**
- Supports nested objects
- Returns NULL if path doesn't exist
- Returns stringified JSON for complex values

---

### Encryption Functions (Enterprise)

> **Note:** These functions are only available in OpenObserve Enterprise Edition

#### `decrypt_path(field, key_name, path)`

**Description:** Decrypts a field at a specified JSON path using a named encryption key.

**Signature:**
```sql
decrypt_path(field: STRING, key_name: STRING, path: STRING) -> STRING
```

**Parameters:**
- `field`: JSON field containing encrypted data
- `key_name`: Name of the encryption key to use
- `path`: JSON path to the encrypted field

**Returns:** Decrypted value as string

**Example:**
```sql
SELECT decrypt_path(user_data, 'user_key', 'ssn') as ssn FROM users
```

**Notes:**
- Enterprise feature only
- Supports nested paths and arrays
- Returns NULL if decryption fails

---

#### `encrypt(field, key_name, path)`

**Description:** Encrypts a field at a specified JSON path using a named encryption key.

**Signature:**
```sql
encrypt(field: STRING, key_name: STRING, path: STRING) -> STRING
```

**Parameters:**
- `field`: JSON field to encrypt
- `key_name`: Name of the encryption key to use
- `path`: JSON path to the field to encrypt

**Returns:** Field with encrypted value

**Example:**
```sql
SELECT encrypt(user_data, 'user_key', 'ssn') as encrypted_data FROM users
```

---

#### `decrypt(field, key_name)` [SLOW]

**Description:** Brute-force decryption function that scans for base64 segments and attempts to decrypt them.

**Signature:**
```sql
decrypt(field: STRING, key_name: STRING) -> STRING
```

**Parameters:**
- `field`: Field containing encrypted data (base64 encoded segments)
- `key_name`: Name of the encryption key to use

**Returns:** Field with decrypted values

**Example:**
```sql
SELECT decrypt(log_message, 'default_key') FROM logs
```

**Notes:**
- **WARNING:** This is a slow operation as it scans the entire field
- Use `decrypt_path` when possible for better performance
- Attempts to find and decrypt any base64-encoded segments

---

### Other Functions

#### `transform_*` (VRL Functions)

**Description:** Dynamic user-defined functions using Vector Routing Language (VRL).

**Signature:**
```sql
transform_<name>(args...) -> STRING
```

**Parameters:**
- Variable number of string arguments depending on the VRL function definition

**Returns:** String result from VRL function execution

**Example:**
```sql
-- If a custom VRL function 'parse_url' is defined:
SELECT transform_parse_url(url_field) as parsed_url FROM logs
```

**Notes:**
- Functions are dynamically created from the QUERY_FUNCTIONS registry
- Each organization can define custom VRL transforms
- Function names are prefixed with `transform_`

---

## Aggregate Functions (UDAFs)

### `percentile_cont(value, percentile)`

**Description:** Computes the exact percentile of a numeric column using linear interpolation (continuous percentile). This replaces the `percentile_cont` function from Apache Datafusion.

**Signature:**
```sql
percentile_cont(value: NUMERIC, percentile: FLOAT64) -> NUMERIC
```

**Parameters:**
- `value`: Numeric column to compute percentile on
- `percentile`: Percentile level (0.0 to 1.0, e.g., 0.5 for median, 0.95 for 95th percentile)

**Returns:** Percentile value in the same data type as input

**Example:**
```sql
-- Calculate median response time
SELECT percentile_cont(response_time, 0.5) as median_response_time
FROM requests

-- Calculate 95th percentile
SELECT percentile_cont(response_time, 0.95) as p95_response_time
FROM requests

-- Multiple percentiles
SELECT 
  percentile_cont(response_time, 0.5) as p50,
  percentile_cont(response_time, 0.95) as p95,
  percentile_cont(response_time, 0.99) as p99
FROM requests
```

**Notes:**
- Exact percentile calculation (not approximate)
- Uses linear interpolation between values
- Percentile must be between 0.0 and 1.0
- Supports all numeric types: Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64, Float32, Float64

---

### `summary_percentile(value, count, percentile)`

**Description:** Computes percentile from pre-aggregated summary data (value-count pairs).

**Signature:**
```sql
summary_percentile(value: NUMERIC, count: INT64, percentile: FLOAT64) -> NUMERIC
```

**Parameters:**
- `value`: Numeric value from pre-aggregated data
- `count`: Total count associated with the value
- `percentile`: Percentile level (0.0 to 1.0)

**Returns:** Percentile value

**Example:**
```sql
-- When data is already grouped with counts
SELECT summary_percentile(bucket_value, bucket_count, 0.95) as p95
FROM aggregated_metrics
```

**Notes:**
- Used for computing percentiles from pre-aggregated data
- Useful when data comes from histograms or pre-calculated summaries
- More efficient than `percentile_cont` of datafusion when working with summarized data

---

## Function Categories Summary

| Category | Functions |
|----------|-----------|
| **Array Manipulation** | `arr_descending`, `arrcount`, `arrindex`, `arrjoin`, `arrsort`, `arrzip`, `cast_to_arr`, `to_array_string`, `string_to_array_v2` |
| **String Matching** | `str_match`, `str_match_ignore_case`, `match_all`, `fuzzy_match`, `fuzzy_match_all` |
| **Regular Expressions** | `re_match`, `re_not_match`, `re_matches` |
| **Date/Time** | `cast_to_timestamp`, `date_format`, `time_range`, `histogram` |
| **JSON** | `spath` |
| **Encryption** | `decrypt_path`, `encrypt`, `decrypt` (Enterprise only) |
| **Aggregation** | `percentile_cont`, `summary_percentile` |
| **User-Defined** | `transform_*` (VRL-based) |

---

## Usage Tips

1. **Array Functions**: Most array functions expect JSON string representations and return JSON strings. Use `cast_to_arr` to convert to native DataFusion arrays when needed.

2. **String Matching**: For full-text search, `match_all` and `fuzzy_match_all` are most efficient. For specific field matching, use `str_match` or regex functions.

3. **Timestamps**: Always use `cast_to_timestamp` for timestamp conversions to ensure compatibility with OpenObserve's internal timestamp format (microseconds).

4. **Performance**: Regular functions (UDFs) are generally faster than aggregate functions (UDAFs). Regex functions (`re_match`, `re_not_match`) are optimized but still more expensive than simple string matching.

5. **NULL Handling**: Most functions return NULL when given NULL inputs or when encountering errors (e.g., invalid JSON). Always consider NULL handling in your queries.

---

## See Also

- [Apache DataFusion Documentation](https://arrow.apache.org/datafusion/)
- [OpenObserve Query Documentation](https://openobserve.ai/docs/query)
- [VRL (Vector Routing Language) Documentation](https://vector.dev/docs/reference/vrl/)
