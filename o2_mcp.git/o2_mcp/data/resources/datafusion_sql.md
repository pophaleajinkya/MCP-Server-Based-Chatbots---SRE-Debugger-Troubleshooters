# DataFusion SQL Reference

> This document provides SQL function references for Apache DataFusion,
> the query engine used by OpenObserve. Use this reference when constructing
> SQL queries for log analysis, metrics aggregation, and data exploration.

---

## Table of Contents

- [Aggregate Functions](#aggregate-functions)
  - [Approximate Functions](#aggregate-functions-approximate-functions) (4 functions)
  - [General Functions](#aggregate-functions-general-functions) (19 functions)
  - [Statistical Functions](#aggregate-functions-statistical-functions) (15 functions)
- [Operators](#operators)
  - [Literals](#operators-literals) (1 functions)
  - [Logical Operators](#operators-logical-operators) (2 functions)
- [SELECT](#select)
  - [Pipe operators](#select-pipe-operators) (9 functions)
- [Scalar Functions](#scalar-functions)
  - [Array Functions](#scalar-functions-array-functions) (41 functions)
  - [Binary String Functions](#scalar-functions-binary-string-functions) (2 functions)
  - [Conditional Functions](#scalar-functions-conditional-functions) (5 functions)
  - [Hashing Functions](#scalar-functions-hashing-functions) (6 functions)
  - [Map Functions](#scalar-functions-map-functions) (5 functions)
  - [Math Functions](#scalar-functions-math-functions) (38 functions)
  - [Other Functions](#scalar-functions-other-functions) (5 functions)
  - [Regular Expression Functions](#scalar-functions-regular-expression-functions) (1 functions)
  - [String Functions](#scalar-functions-string-functions) (32 functions)
  - [Struct Functions](#scalar-functions-struct-functions) (2 functions)
  - [Time and Date Functions](#scalar-functions-time-and-date-functions) (19 functions)
  - [Union Functions](#scalar-functions-union-functions) (2 functions)
- [Special Functions](#special-functions)
  - [Expansion Functions](#special-functions-expansion-functions) (1 functions)
- [Subqueries](#subqueries)
  - [FROM clause subqueries](#subqueries-from-clause-subqueries) (1 functions)
  - [HAVING clause subqueries](#subqueries-having-clause-subqueries) (1 functions)
  - [SELECT clause subqueries](#subqueries-select-clause-subqueries) (1 functions)
- [Window Functions](#window-functions)
  - [Analytical Functions](#window-functions-analytical-functions) (5 functions)
  - [Ranking Functions](#window-functions-ranking-functions) (6 functions)

---

## Quick Reference

### Common Query Patterns

#### Time-based Filtering
```sql
-- Filter logs from last 24 hours
SELECT * FROM logs
WHERE _timestamp >= now() - interval '24 hours'
ORDER BY _timestamp DESC;
```

#### Time Bucketing / Histogram
```sql
-- Group events by hour
SELECT
    date_trunc('hour', _timestamp) AS hour,
    count(_timestamp) AS event_count
FROM logs
WHERE _timestamp >= now() - interval '7 days'
GROUP BY 1
ORDER BY 1;
```

#### String Pattern Matching
```sql
-- Find logs containing error patterns
SELECT * FROM logs
WHERE regexp_like(message, 'error|exception|failed', 'i');
```

#### JSON Field Extraction
```sql
-- Extract nested JSON fields
SELECT
    get_field(data, 'user', 'id') AS user_id,
    get_field(data, 'status') AS status
FROM events;
```

#### Aggregation with Filtering
```sql
-- Count events by type, excluding nulls
SELECT
    event_type,
    count(_timestamp) AS total,
    avg(response_time) FILTER (WHERE response_time > 0) AS avg_response
FROM logs
GROUP BY event_type
HAVING count(_timestamp) > 10;
```

---

## Aggregate Functions

### Approximate Functions

**Available functions:** `approx_distinct`, `approx_median`, `approx_percentile_cont`, `approx_percentile_cont_with_weight`

### `approx_distinct`

Returns the approximate number of distinct input values calculated using the HyperLogLog algorithm.

**Syntax:**
```sql
approx_distinct(expression)
```

**Example:**
```sql
SELECT approx_distinct(column_name) FROM table_name;
```

### `approx_median`

Returns the approximate median (50th percentile) of input values. It is an alias of `approx_percentile_cont(0.5) WITHIN GROUP (ORDER BY x)`.

**Syntax:**
```sql
approx_median(expression)
```

**Example:**
```sql
SELECT approx_median(column_name) FROM table_name;
```

### `approx_percentile_cont`

Returns the approximate percentile of input values using the t-digest algorithm.

**Syntax:**
```sql
approx_percentile_cont(percentile [, centroids]) WITHIN GROUP (ORDER BY expression)
```

**Example:**
```sql
SELECT approx_percentile_cont(0.75) WITHIN GROUP (ORDER BY column_name) FROM table_name;
```

### `approx_percentile_cont_with_weight`

Returns the weighted approximate percentile of input values using the t-digest algorithm.

**Syntax:**
```sql
approx_percentile_cont_with_weight(weight, percentile [, centroids]) WITHIN GROUP (ORDER BY expression)
```

**Example:**
```sql
SELECT approx_percentile_cont_with_weight(weight_column, 0.90) WITHIN GROUP (ORDER BY column_name) FROM table_name;
```

### General Functions

**Available functions:** `array_agg`, `avg`, `bit_and`, `bit_or`, `bit_xor`, `bool_and`, `bool_or`, `count`, `first_value`, `grouping`, `last_value`, `max`, `median`, `min`, `percentile_cont`, `string_agg`, `sum`, `var`, `var_pop`

### `array_agg`

Returns an array created from the expression elements. If ordering is required, elements are inserted in the specified order. This aggregation function can only mix DISTINCT and ORDER BY if the ordering expression is exactly the same as the argument expression.

**Syntax:**
```sql
array_agg(expression [ORDER BY expression])
```

**Example:**
```sql
SELECT array_agg(column_name ORDER BY other_column) FROM table_name;
```

### `avg`

Returns the average of numeric values in the specified column.

**Syntax:**
```sql
avg(expression)
```

**Example:**
```sql
SELECT avg(column_name) FROM table_name;
```

### `bit_and`

Computes the bitwise AND of all non-null input values.

**Syntax:**
```sql
bit_and(expression)
```

### `bit_or`

Computes the bitwise OR of all non-null input values.

**Syntax:**
```sql
bit_or(expression)
```

### `bit_xor`

Computes the bitwise exclusive OR of all non-null input values.

**Syntax:**
```sql
bit_xor(expression)
```

### `bool_and`

Returns true if all non-null input values are true, otherwise false.

**Syntax:**
```sql
bool_and(expression)
```

**Example:**
```sql
SELECT bool_and(column_name) FROM table_name;
```

### `bool_or`

Returns true if all non-null input values are true, otherwise false.

**Syntax:**
```sql
bool_and(expression)
```

**Example:**
```sql
SELECT bool_and(column_name) FROM table_name;
```

### `count`

Returns the number of non-null values in the specified column. To include null values in the total count, use `count(*)`.

**Syntax:**
```sql
count(expression)
```

**Example:**
```sql
SELECT count(column_name) FROM table_name;
```

### `first_value`

Returns the first element in an aggregation group according to the requested ordering. If no ordering is given, returns an arbitrary element from the group.

**Syntax:**
```sql
first_value(expression [ORDER BY expression])
```

**Example:**
```sql
SELECT first_value(column_name ORDER BY other_column) FROM table_name;
```

### `grouping`

Returns 1 if the data is aggregated across the specified column, or 0 if it is not aggregated in the result set.

**Syntax:**
```sql
grouping(expression)
```

**Example:**
```sql
SELECT column_name, GROUPING(column_name) AS group_column
 FROM table_name
 GROUP BY GROUPING SETS ((column_name), ());
```

### `last_value`

Returns the last element in an aggregation group according to the requested ordering. If no ordering is given, returns an arbitrary element from the group.

**Syntax:**
```sql
last_value(expression [ORDER BY expression])
```

**Example:**
```sql
SELECT last_value(column_name ORDER BY other_column) FROM table_name;
```

### `max`

Returns the maximum value in the specified column.

**Syntax:**
```sql
max(expression)
```

**Example:**
```sql
SELECT max(column_name) FROM table_name;
```

### `median`

Returns the median value in the specified column.

**Syntax:**
```sql
median(expression)
```

**Example:**
```sql
SELECT median(column_name) FROM table_name;
```

### `min`

Returns the minimum value in the specified column.

**Syntax:**
```sql
min(expression)
```

**Example:**
```sql
SELECT min(column_name) FROM table_name;
```

### `percentile_cont`

Returns the exact percentile of input values, interpolating between values if needed.

**Syntax:**
```sql
percentile_cont(percentile) WITHIN GROUP (ORDER BY expression)
```

**Example:**
```sql
SELECT percentile_cont(0.75) WITHIN GROUP (ORDER BY column_name) FROM table_name;
```

### `string_agg`

Concatenates the values of string expressions and places separator values between them. If ordering is required, strings are concatenated in the specified order. This aggregation function can only mix DISTINCT and ORDER BY if the ordering expression is exactly the same as the first argument expression.

**Syntax:**
```sql
string_agg([DISTINCT] expression, delimiter [ORDER BY expression])
```

**Example:**
```sql
SELECT string_agg(name, ', ') AS names_list
 FROM employee;
```

### `sum`

Returns the sum of all values in the specified column.

**Syntax:**
```sql
sum(expression)
```

**Example:**
```sql
SELECT sum(column_name) FROM table_name;
```

### `var`

Returns the statistical sample variance of a set of numbers.

**Syntax:**
```sql
var(expression)
```

### `var_pop`

Returns the statistical population variance of a set of numbers.

**Syntax:**
```sql
var_pop(expression)
```

### Statistical Functions

**Available functions:** `corr`, `covar_pop`, `covar_samp`, `nth_value`, `regr_avgx`, `regr_avgy`, `regr_count`, `regr_intercept`, `regr_r2`, `regr_slope`, `regr_sxx`, `regr_sxy`, `regr_syy`, `stddev`, `stddev_pop`

### `corr`

Returns the coefficient of correlation between two numeric values.

**Syntax:**
```sql
corr(expression1, expression2)
```

**Example:**
```sql
SELECT corr(column1, column2) FROM table_name;
```

### `covar_pop`

Returns the sample covariance of a set of number pairs.

**Syntax:**
```sql
covar_samp(expression1, expression2)
```

**Example:**
```sql
SELECT covar_samp(column1, column2) FROM table_name;
```

### `covar_samp`

Returns the sample covariance of a set of number pairs.

**Syntax:**
```sql
covar_samp(expression1, expression2)
```

**Example:**
```sql
SELECT covar_samp(column1, column2) FROM table_name;
```

### `nth_value`

Returns the nth value in a group of values.

**Syntax:**
```sql
nth_value(expression, n ORDER BY expression)
```

**Example:**
```sql
SELECT dept_id, salary, NTH_VALUE(salary, 2) OVER (PARTITION BY dept_id ORDER BY salary ASC) AS second_salary_by_dept
 FROM employee;
```

### `regr_avgx`

Computes the average of the independent variable (input) expression_x for the non-null paired data points.

**Syntax:**
```sql
regr_avgx(expression_y, expression_x)
```

**Example:**
```sql
select * from daily_sales;
```

### `regr_avgy`

Computes the average of the dependent variable (output) expression_y for the non-null paired data points.

**Syntax:**
```sql
regr_avgy(expression_y, expression_x)
```

**Example:**
```sql
select * from daily_temperature;
```

### `regr_count`

Counts the number of non-null paired data points.

**Syntax:**
```sql
regr_count(expression_y, expression_x)
```

**Example:**
```sql
select * from daily_metrics;
```

### `regr_intercept`

Computes the y-intercept of the linear regression line. For the equation (y = kx + b), this function returns b.

**Syntax:**
```sql
regr_intercept(expression_y, expression_x)
```

**Example:**
```sql
select * from weekly_performance;
```

### `regr_r2`

Computes the square of the correlation coefficient between the independent and dependent variables.

**Syntax:**
```sql
regr_r2(expression_y, expression_x)
```

**Example:**
```sql
select * from weekly_performance;
```

### `regr_slope`

Returns the slope of the linear regression line for non-null pairs in aggregate columns. Given input column Y and X: regr_slope(Y, X) returns the slope (k in Y = k\*X + b) using minimal RSS fitting.

**Syntax:**
```sql
regr_slope(expression_y, expression_x)
```

**Example:**
```sql
select * from weekly_performance;
```

### `regr_sxx`

Computes the sum of squares of the independent variable.

**Syntax:**
```sql
regr_sxx(expression_y, expression_x)
```

**Example:**
```sql
select * from study_hours;
```

### `regr_sxy`

Computes the sum of products of paired data points.

**Syntax:**
```sql
regr_sxy(expression_y, expression_x)
```

**Example:**
```sql
select * from employee_productivity;
```

### `regr_syy`

Computes the sum of squares of the dependent variable.

**Syntax:**
```sql
regr_syy(expression_y, expression_x)
```

**Example:**
```sql
select * from employee_productivity;
```

### `stddev`

Returns the standard deviation of a set of numbers.

**Syntax:**
```sql
stddev(expression)
```

**Example:**
```sql
SELECT stddev(column_name) FROM table_name;
```

### `stddev_pop`

Returns the population standard deviation of a set of numbers.

**Syntax:**
```sql
stddev_pop(expression)
```

**Example:**
```sql
SELECT stddev_pop(column_name) FROM table_name;
```

---

## Operators

### Literals

**Available functions:** `escaping`

### `escaping`

Unlike many other languages, SQL literals do not by default support C-style escape sequences such as `\n` for newline. Instead all characters in a `'` string are treated literally. To escape `'` in SQL literals, use `''`:

**Syntax:**
```sql
> select 'it''s escaped';
```

### Logical Operators

**Available functions:** `and`, `or`

### `and`

Logical And

**Syntax:**
```sql
> SELECT true AND true;
```

### `or`

Logical Or

**Syntax:**
```sql
> SELECT false OR true;
```

---

## SELECT

### Pipe operators

**Available functions:** `aggregate`, `as`, `except`, `extend`, `intersect`, `join`, `limit`, `select`, `union`

### `aggregate`

```sql select * from range(0,3) |> aggregate sum(value) AS total; +-------+ | total | +-------+ | 3 | +-------+ ``` (pipe_join)=

**Syntax:**
```sql
select * from range(0,3)
```

### `as`

```sql select * from range(0,3) |> as my_range |> SELECT my_range.value; +-------+ | value | +-------+ | 0 | | 1 | | 2 | +-------+ ``` (pipe_union)=

**Syntax:**
```sql
select * from range(0,3)
```

### `except`

```sql select * from range(0,10) |> EXCEPT DISTINCT (select * from range(5,10)); +-------+ | value | +-------+ | 0 | | 1 | | 2 | | 3 | | 4 | +-------+ ``` (pipe_aggregate)=

**Syntax:**
```sql
select * from range(0,10)
```

### `extend`

```sql select * from range(0,3) |> extend -value AS minus_value; +-------+-------------+ | value | minus_value | +-------+-------------+ | 0 | 0 | | 1 | -1 | | 2 | -2 | +-------+-------------+ ``` (pipe_as)=

**Syntax:**
```sql
select * from range(0,3)
```

### `intersect`

```sql select * from range(0,100) |> INTERSECT DISTINCT ( select 3 ); +-------+ | value | +-------+ | 3 | +-------+ ``` (pipe_except)=

**Syntax:**
```sql
select * from range(0,100)
```

### `join`

```sql ( SELECT 'apples' AS item, 2 AS sales UNION ALL SELECT 'bananas' AS item, 5 AS sales ) |> AS produce_sales |> LEFT JOIN ( SELECT 'apples' AS item, 123 AS id ) AS produce_data ON produce_sales.item = produce_data.item |> SELECT produce_sales.item, sales, id; +--------+-------+------+ | item | sales | id | +--------+-------+------+ | apples | 2 | 123 | | bananas| 5 | NULL | +--------+-------+------+ ```

**Syntax:**
```sql
(
```

### `limit`

```sql select * from range(0,3) |> order by value desc |> limit 1; +-------+ | value | +-------+ | 2 | +-------+ ``` (pipe_select)=

**Syntax:**
```sql
select * from range(0,3)
```

### `select`

```sql select * from range(0,3) |> select value + 10; +---------------------------+ | range().value + Int64(10) | +---------------------------+ | 10 | | 11 | | 12 | +---------------------------+ ``` (pipe_extend)=

**Syntax:**
```sql
select * from range(0,3)
```

### `union`

```sql select * from range(0,3) |> union all ( select * from range(3,6) ); +-------+ | value | +-------+ | 0 | | 1 | | 2 | | 3 | | 4 | | 5 | +-------+ ``` (pipe_intersect)=

**Syntax:**
```sql
select * from range(0,3)
```

---

## Scalar Functions

### Array Functions

**Available functions:** `array_any_value`, `array_append`, `array_concat`, `array_dims`, `array_distance`, `array_distinct`, `array_element`, `array_except`, `array_has`, `array_has_all`, `array_has_any`, `array_intersect`, `array_length`, `array_max`, `array_min`, `array_ndims`, `array_pop_back`, `array_pop_front`, `array_position`, `array_positions`, `array_prepend`, `array_remove`, `array_remove_all`, `array_remove_n`, `array_repeat`, `array_replace`, `array_replace_all`, `array_replace_n`, `array_resize`, `array_reverse`, `array_slice`, `array_sort`, `array_to_string`, `array_union`, `cardinality`, `empty`, `flatten`, `generate_series`, `make_array`, `range`, `string_to_array`

### `array_any_value`

Returns the first non-null element in the array.

**Syntax:**
```sql
array_any_value(array)
```

**Example:**
```sql
select array_any_value([NULL, 1, 2, 3]);
```

### `array_append`

Appends an element to the end of an array.

**Syntax:**
```sql
array_append(array, element)
```

**Example:**
```sql
select array_append([1, 2, 3], 4);
```

### `array_concat`

Concatenates arrays.

**Syntax:**
```sql
array_concat(array[, ..., array_n])
```

**Example:**
```sql
select array_concat([1, 2], [3, 4], [5, 6]);
```

### `array_dims`

Returns an array of the array's dimensions.

**Syntax:**
```sql
array_dims(array)
```

**Example:**
```sql
select array_dims([[1, 2, 3], [4, 5, 6]]);
```

### `array_distance`

Returns the Euclidean distance between two input arrays of equal length.

**Syntax:**
```sql
array_distance(array1, array2)
```

**Example:**
```sql
select array_distance([1, 2], [1, 4]);
```

### `array_distinct`

Returns distinct values from the array after removing duplicates.

**Syntax:**
```sql
array_distinct(array)
```

**Example:**
```sql
select array_distinct([1, 3, 2, 3, 1, 2, 4]);
```

### `array_element`

Extracts the element with the index n from the array.

**Syntax:**
```sql
array_element(array, index)
```

**Example:**
```sql
select array_element([1, 2, 3, 4], 3);
```

### `array_except`

Returns an array of the elements that appear in the first array but not in the second.

**Syntax:**
```sql
array_except(array1, array2)
```

**Example:**
```sql
select array_except([1, 2, 3, 4], [5, 6, 3, 4]);
```

### `array_has`

Returns true if the array contains the element.

**Syntax:**
```sql
array_has(array, element)
```

**Example:**
```sql
select array_has([1, 2, 3], 2);
```

### `array_has_all`

Returns true if all elements of sub-array exist in array.

**Syntax:**
```sql
array_has_all(array, sub-array)
```

**Example:**
```sql
select array_has_all([1, 2, 3, 4], [2, 3]);
```

### `array_has_any`

Returns true if any elements exist in both arrays.

**Syntax:**
```sql
array_has_any(array, sub-array)
```

**Example:**
```sql
select array_has_any([1, 2, 3], [3, 4]);
```

### `array_intersect`

Returns an array of elements in the intersection of array1 and array2.

**Syntax:**
```sql
array_intersect(array1, array2)
```

**Example:**
```sql
select array_intersect([1, 2, 3, 4], [5, 6, 3, 4]);
```

### `array_length`

Returns the length of the array dimension.

**Syntax:**
```sql
array_length(array, dimension)
```

**Example:**
```sql
select array_length([1, 2, 3, 4, 5], 1);
```

### `array_max`

Returns the maximum value in the array.

**Syntax:**
```sql
array_max(array)
```

**Example:**
```sql
select array_max([3,1,4,2]);
```

### `array_min`

Returns the minimum value in the array.

**Syntax:**
```sql
array_min(array)
```

**Example:**
```sql
select array_min([3,1,4,2]);
```

### `array_ndims`

Returns the number of dimensions of the array.

**Syntax:**
```sql
array_ndims(array, element)
```

**Example:**
```sql
select array_ndims([[1, 2, 3], [4, 5, 6]]);
```

### `array_pop_back`

Returns the array without the last element.

**Syntax:**
```sql
array_pop_back(array)
```

**Example:**
```sql
select array_pop_back([1, 2, 3]);
```

### `array_pop_front`

Returns the array without the first element.

**Syntax:**
```sql
array_pop_front(array)
```

**Example:**
```sql
select array_pop_front([1, 2, 3]);
```

### `array_position`

Returns the position of the first occurrence of the specified element in the array, or NULL if not found.

**Syntax:**
```sql
array_position(array, element)
```

**Example:**
```sql
select array_position([1, 2, 2, 3, 1, 4], 2);
```

### `array_positions`

Searches for an element in the array, returns all occurrences.

**Syntax:**
```sql
array_positions(array, element)
```

**Example:**
```sql
select array_positions([1, 2, 2, 3, 1, 4], 2);
```

### `array_prepend`

Prepends an element to the beginning of an array.

**Syntax:**
```sql
array_prepend(element, array)
```

**Example:**
```sql
select array_prepend(1, [2, 3, 4]);
```

### `array_remove`

Removes the first element from the array equal to the given value.

**Syntax:**
```sql
array_remove(array, element)
```

**Example:**
```sql
select array_remove([1, 2, 2, 3, 2, 1, 4], 2);
```

### `array_remove_all`

Removes all elements from the array equal to the given value.

**Syntax:**
```sql
array_remove_all(array, element)
```

**Example:**
```sql
select array_remove_all([1, 2, 2, 3, 2, 1, 4], 2);
```

### `array_remove_n`

Removes the first `max` elements from the array equal to the given value.

**Syntax:**
```sql
array_remove_n(array, element, max))
```

**Example:**
```sql
select array_remove_n([1, 2, 2, 3, 2, 1, 4], 2, 2);
```

### `array_repeat`

Returns an array containing element `count` times.

**Syntax:**
```sql
array_repeat(element, count)
```

**Example:**
```sql
select array_repeat(1, 3);
```

### `array_replace`

Replaces the first occurrence of the specified element with another specified element.

**Syntax:**
```sql
array_replace(array, from, to)
```

**Example:**
```sql
select array_replace([1, 2, 2, 3, 2, 1, 4], 2, 5);
```

### `array_replace_all`

Replaces all occurrences of the specified element with another specified element.

**Syntax:**
```sql
array_replace_all(array, from, to)
```

**Example:**
```sql
select array_replace_all([1, 2, 2, 3, 2, 1, 4], 2, 5);
```

### `array_replace_n`

Replaces the first `max` occurrences of the specified element with another specified element.

**Syntax:**
```sql
array_replace_n(array, from, to, max)
```

**Example:**
```sql
select array_replace_n([1, 2, 2, 3, 2, 1, 4], 2, 5, 2);
```

### `array_resize`

Resizes the list to contain size elements. Initializes new elements with value or empty if value is not set.

**Syntax:**
```sql
array_resize(array, size, value)
```

**Example:**
```sql
select array_resize([1, 2, 3], 5, 0);
```

### `array_reverse`

Returns the array with the order of the elements reversed.

**Syntax:**
```sql
array_reverse(array)
```

**Example:**
```sql
select array_reverse([1, 2, 3, 4]);
```

### `array_slice`

Returns a slice of the array based on 1-indexed start and end positions.

**Syntax:**
```sql
array_slice(array, begin, end)
```

**Example:**
```sql
select array_slice([1, 2, 3, 4, 5, 6, 7, 8], 3, 6);
```

### `array_sort`

Sort array.

**Syntax:**
```sql
array_sort(array, desc, nulls_first)
```

**Example:**
```sql
select array_sort([3, 1, 2]);
```

### `array_to_string`

Converts each element to its text representation.

**Syntax:**
```sql
array_to_string(array, delimiter[, null_string])
```

**Example:**
```sql
select array_to_string([[1, 2, 3, 4], [5, 6, 7, 8]], ',');
```

### `array_union`

Returns an array of elements that are present in both arrays (all elements from both arrays) without duplicates.

**Syntax:**
```sql
array_union(array1, array2)
```

**Example:**
```sql
select array_union([1, 2, 3, 4], [5, 6, 3, 4]);
```

### `cardinality`

Returns the total number of elements in the array.

**Syntax:**
```sql
cardinality(array)
```

**Example:**
```sql
select cardinality([[1, 2, 3, 4], [5, 6, 7, 8]]);
```

### `empty`

Returns 1 for an empty array or 0 for a non-empty array.

**Syntax:**
```sql
empty(array)
```

**Example:**
```sql
select empty([1]);
```

### `flatten`

Converts an array of arrays to a flat array. - Applies to any depth of nested arrays - Does not change arrays that are already flat The flattened array contains all the elements from all source arrays.

**Syntax:**
```sql
flatten(array)
```

**Example:**
```sql
select flatten([[1, 2], [3, 4]]);
```

### `generate_series`

Similar to the range function, but it includes the upper bound.

**Syntax:**
```sql
generate_series(stop)
```

**Example:**
```sql
select generate_series(1,3);
```

### `make_array`

Returns an array using the specified input expressions.

**Syntax:**
```sql
make_array(expression1[, ..., expression_n])
```

**Example:**
```sql
select make_array(1, 2, 3, 4, 5);
```

### `range`

Returns an Arrow array between start and stop with step. The range start..end contains all values with start <= x < end. It is empty if start >= end. Step cannot be 0.

**Syntax:**
```sql
range(stop)
```

**Example:**
```sql
select range(2, 10, 3);
```

### `string_to_array`

Splits a string into an array of substrings based on a delimiter. Any substrings matching the optional `null_str` argument are replaced with NULL.

**Syntax:**
```sql
string_to_array(str, delimiter[, null_str])
```

**Example:**
```sql
select string_to_array('abc##def', '##');
```

### Binary String Functions

**Available functions:** `decode`, `encode`

### `decode`

Decode binary data from textual representation in string.

**Syntax:**
```sql
decode(expression, format)
```

### `encode`

Encode binary data into a textual representation.

**Syntax:**
```sql
encode(expression, format)
```

### Conditional Functions

**Available functions:** `coalesce`, `greatest`, `least`, `nvl`, `nvl2`

### `coalesce`

Returns the first of its arguments that is not _null_. Returns _null_ if all arguments are _null_. This function is often used to substitute a default value for _null_ values.

**Syntax:**
```sql
coalesce(expression1[, ..., expression_n])
```

**Example:**
```sql
select coalesce(null, null, 'datafusion');
```

### `greatest`

Returns the greatest value in a list of expressions. Returns _null_ if all expressions are _null_.

**Syntax:**
```sql
greatest(expression1[, ..., expression_n])
```

**Example:**
```sql
select greatest(4, 7, 5);
```

### `least`

Returns the smallest value in a list of expressions. Returns _null_ if all expressions are _null_.

**Syntax:**
```sql
least(expression1[, ..., expression_n])
```

**Example:**
```sql
select least(4, 7, 5);
```

### `nvl`

Returns _expression2_ if _expression1_ is NULL otherwise it returns _expression1_ and _expression2_ is not evaluated. This function can be used to substitute a default value for NULL values.

**Syntax:**
```sql
nvl(expression1, expression2)
```

**Example:**
```sql
select nvl(null, 'a');
```

### `nvl2`

Returns _expression2_ if _expression1_ is not NULL; otherwise it returns _expression3_.

**Syntax:**
```sql
nvl2(expression1, expression2, expression3)
```

**Example:**
```sql
select nvl2(null, 'a', 'b');
```

### Hashing Functions

**Available functions:** `digest`, `md5`, `sha224`, `sha256`, `sha384`, `sha512`

### `digest`

Computes the binary hash of an expression using the specified algorithm.

**Syntax:**
```sql
digest(expression, algorithm)
```

**Example:**
```sql
select digest('foo', 'sha256');
```

### `md5`

Computes an MD5 128-bit checksum for a string expression.

**Syntax:**
```sql
md5(expression)
```

**Example:**
```sql
select md5('foo');
```

### `sha224`

Computes the SHA-224 hash of a binary string.

**Syntax:**
```sql
sha224(expression)
```

**Example:**
```sql
select sha224('foo');
```

### `sha256`

Computes the SHA-256 hash of a binary string.

**Syntax:**
```sql
sha256(expression)
```

**Example:**
```sql
select sha256('foo');
```

### `sha384`

Computes the SHA-384 hash of a binary string.

**Syntax:**
```sql
sha384(expression)
```

**Example:**
```sql
select sha384('foo');
```

### `sha512`

Computes the SHA-512 hash of a binary string.

**Syntax:**
```sql
sha512(expression)
```

**Example:**
```sql
select sha512('foo');
```

### Map Functions

**Available functions:** `map`, `map_entries`, `map_extract`, `map_keys`, `map_values`

### `map`

Returns an Arrow map with the specified key-value pairs. The `make_map` function creates a map from two lists: one for keys and one for values. Each key must be unique and non-null.

**Syntax:**
```sql
map(key, value)
```

**Example:**
```sql
SELECT MAP('type', 'test');
```

### `map_entries`

Returns a list of all entries in the map.

**Syntax:**
```sql
map_entries(map)
```

**Example:**
```sql
SELECT map_entries(MAP {'a': 1, 'b': NULL, 'c': 3});
```

### `map_extract`

Returns a list containing the value for the given key or an empty list if the key is not present in the map.

**Syntax:**
```sql
map_extract(map, key)
```

**Example:**
```sql
SELECT map_extract(MAP {'a': 1, 'b': NULL, 'c': 3}, 'a');
```

### `map_keys`

Returns a list of all keys in the map.

**Syntax:**
```sql
map_keys(map)
```

**Example:**
```sql
SELECT map_keys(MAP {'a': 1, 'b': NULL, 'c': 3});
```

### `map_values`

Returns a list of all values in the map.

**Syntax:**
```sql
map_values(map)
```

**Example:**
```sql
SELECT map_values(MAP {'a': 1, 'b': NULL, 'c': 3});
```

### Math Functions

**Available functions:** `abs`, `acos`, `acosh`, `asin`, `asinh`, `atan`, `atan2`, `atanh`, `cbrt`, `ceil`, `cos`, `cosh`, `cot`, `degrees`, `exp`, `factorial`, `floor`, `gcd`, `isnan`, `iszero`, `lcm`, `ln`, `log`, `log10`, `log2`, `nanvl`, `pi`, `power`, `radians`, `random`, `round`, `signum`, `sin`, `sinh`, `sqrt`, `tan`, `tanh`, `trunc`

### `abs`

Returns the absolute value of a number.

**Syntax:**
```sql
abs(numeric_expression)
```

**Example:**
```sql
SELECT abs(-5);
```

### `acos`

Returns the arc cosine or inverse cosine of a number.

**Syntax:**
```sql
acos(numeric_expression)
```

**Example:**
```sql
SELECT acos(1);
```

### `acosh`

Returns the area hyperbolic cosine or inverse hyperbolic cosine of a number.

**Syntax:**
```sql
acosh(numeric_expression)
```

**Example:**
```sql
SELECT acosh(2);
```

### `asin`

Returns the arc sine or inverse sine of a number.

**Syntax:**
```sql
asin(numeric_expression)
```

**Example:**
```sql
SELECT asin(0.5);
```

### `asinh`

Returns the area hyperbolic sine or inverse hyperbolic sine of a number.

**Syntax:**
```sql
asinh(numeric_expression)
```

**Example:**
```sql
SELECT asinh(1);
```

### `atan`

Returns the arc tangent or inverse tangent of a number.

**Syntax:**
```sql
atan(numeric_expression)
```

**Example:**
```sql
SELECT atan(1);
```

### `atan2`

Returns the arc tangent or inverse tangent of `expression_y / expression_x`.

**Syntax:**
```sql
atan2(expression_y, expression_x)
```

**Example:**
```sql
SELECT atan2(1, 1);
```

### `atanh`

Returns the area hyperbolic tangent or inverse hyperbolic tangent of a number.

**Syntax:**
```sql
atanh(numeric_expression)
```

**Example:**
```sql
SELECT atanh(0.5);
```

### `cbrt`

Returns the cube root of a number.

**Syntax:**
```sql
cbrt(numeric_expression)
```

**Example:**
```sql
SELECT cbrt(27);
```

### `ceil`

Returns the nearest integer greater than or equal to a number.

**Syntax:**
```sql
ceil(numeric_expression)
```

**Example:**
```sql
SELECT ceil(3.14);
```

### `cos`

Returns the cosine of a number.

**Syntax:**
```sql
cos(numeric_expression)
```

**Example:**
```sql
SELECT cos(0);
```

### `cosh`

Returns the hyperbolic cosine of a number.

**Syntax:**
```sql
cosh(numeric_expression)
```

**Example:**
```sql
SELECT cosh(1);
```

### `cot`

Returns the cotangent of a number.

**Syntax:**
```sql
cot(numeric_expression)
```

**Example:**
```sql
SELECT cot(1);
```

### `degrees`

Converts radians to degrees.

**Syntax:**
```sql
degrees(numeric_expression)
```

**Example:**
```sql
SELECT degrees(pi());
```

### `exp`

Returns the base-e exponential of a number.

**Syntax:**
```sql
exp(numeric_expression)
```

**Example:**
```sql
SELECT exp(1);
```

### `factorial`

Factorial. Returns 1 if value is less than 2.

**Syntax:**
```sql
factorial(numeric_expression)
```

**Example:**
```sql
SELECT factorial(5);
```

### `floor`

Returns the nearest integer less than or equal to a number.

**Syntax:**
```sql
floor(numeric_expression)
```

**Example:**
```sql
SELECT floor(3.14);
```

### `gcd`

Returns the greatest common divisor of `expression_x` and `expression_y`. Returns 0 if both inputs are zero.

**Syntax:**
```sql
gcd(expression_x, expression_y)
```

**Example:**
```sql
SELECT gcd(48, 18);
```

### `isnan`

Returns true if a given number is +NaN or -NaN otherwise returns false.

**Syntax:**
```sql
isnan(numeric_expression)
```

**Example:**
```sql
SELECT isnan(1);
```

### `iszero`

Returns true if a given number is +0.0 or -0.0 otherwise returns false.

**Syntax:**
```sql
iszero(numeric_expression)
```

**Example:**
```sql
SELECT iszero(0);
```

### `lcm`

Returns the least common multiple of `expression_x` and `expression_y`. Returns 0 if either input is zero.

**Syntax:**
```sql
lcm(expression_x, expression_y)
```

**Example:**
```sql
SELECT lcm(4, 5);
```

### `ln`

Returns the natural logarithm of a number.

**Syntax:**
```sql
ln(numeric_expression)
```

**Example:**
```sql
SELECT ln(2.71828);
```

### `log`

Returns the base-x logarithm of a number. Can either provide a specified base, or if omitted then takes the base-10 of a number.

**Syntax:**
```sql
log(base, numeric_expression)
```

**Example:**
```sql
SELECT log(10);
```

### `log10`

Returns the base-10 logarithm of a number.

**Syntax:**
```sql
log10(numeric_expression)
```

**Example:**
```sql
SELECT log10(100);
```

### `log2`

Returns the base-2 logarithm of a number.

**Syntax:**
```sql
log2(numeric_expression)
```

**Example:**
```sql
SELECT log2(8);
```

### `nanvl`

Returns the first argument if it's not _NaN_. Returns the second argument otherwise.

**Syntax:**
```sql
nanvl(expression_x, expression_y)
```

**Example:**
```sql
SELECT nanvl(0, 5);
```

### `pi`

Returns an approximate value of π.

**Syntax:**
```sql
pi()
```

### `power`

Returns a base expression raised to the power of an exponent.

**Syntax:**
```sql
power(base, exponent)
```

**Example:**
```sql
SELECT power(2, 3);
```

### `radians`

Converts degrees to radians.

**Syntax:**
```sql
radians(numeric_expression)
```

**Example:**
```sql
SELECT radians(180);
```

### `random`

Returns a random float value in the range [0, 1). The random seed is unique to each row.

**Syntax:**
```sql
random()
```

**Example:**
```sql
SELECT random();
```

### `round`

Rounds a number to the nearest integer.

**Syntax:**
```sql
round(numeric_expression[, decimal_places])
```

**Example:**
```sql
SELECT round(3.14159);
```

### `signum`

Returns the sign of a number. Negative numbers return `-1`. Zero and positive numbers return `1`.

**Syntax:**
```sql
signum(numeric_expression)
```

**Example:**
```sql
SELECT signum(-42);
```

### `sin`

Returns the sine of a number.

**Syntax:**
```sql
sin(numeric_expression)
```

**Example:**
```sql
SELECT sin(0);
```

### `sinh`

Returns the hyperbolic sine of a number.

**Syntax:**
```sql
sinh(numeric_expression)
```

**Example:**
```sql
SELECT sinh(1);
```

### `sqrt`

Returns the square root of a number.

**Syntax:**
```sql
sqrt(numeric_expression)
```

### `tan`

Returns the tangent of a number.

**Syntax:**
```sql
tan(numeric_expression)
```

**Example:**
```sql
SELECT tan(pi()/4);
```

### `tanh`

Returns the hyperbolic tangent of a number.

**Syntax:**
```sql
tanh(numeric_expression)
```

**Example:**
```sql
SELECT tanh(20);
```

### `trunc`

Truncates a number to a whole number or truncated to the specified decimal places.

**Syntax:**
```sql
trunc(numeric_expression[, decimal_places])
```

**Example:**
```sql
SELECT trunc(42.738);
```

### Other Functions

**Available functions:** `arrow_cast`, `arrow_metadata`, `arrow_typeof`, `get_field`, `version`

### `arrow_cast`

Casts a value to a specific Arrow data type.

**Syntax:**
```sql
arrow_cast(expression, datatype)
```

**Example:**
```sql
select
 arrow_cast(-5, 'Int8') as a,
 arrow_cast('foo', 'Dictionary(Int32, Utf8)') as b,
 arrow_cast('bar', 'LargeUtf8') as c;
```

### `arrow_metadata`

Returns the metadata of the input expression. If a key is provided, returns the value for that key. If no key is provided, returns a Map of all metadata.

**Syntax:**
```sql
arrow_metadata(expression[, key])
```

**Example:**
```sql
select arrow_metadata(col) from table;
```

### `arrow_typeof`

Returns the name of the underlying [Arrow data type](https://docs.rs/arrow/latest/arrow/datatypes/enum.DataType.html) of the expression.

**Syntax:**
```sql
arrow_typeof(expression)
```

**Example:**
```sql
select arrow_typeof('foo'), arrow_typeof(1);
```

### `get_field`

Returns a field within a map or a struct with the given key. Supports nested field access by providing multiple field names. Note: most users invoke `get_field` indirectly via field access syntax such as `my_struct_col['field_name']` which results in a call to `get_field(my_struct_col, 'field_name')`. Nested access like `my_struct['a']['b']` is optimized to a single call: `get_field(my_struct, 'a', 'b')`.

**Syntax:**
```sql
get_field(expression, field_name[, field_name2, ...])
```

**Example:**
```sql
select struct_col from test;
```

### `version`

Returns the version of DataFusion.

**Syntax:**
```sql
version()
```

**Example:**
```sql
select version();
```

### Regular Expression Functions

**Available functions:** `regexp_instr`

### `regexp_instr`

Returns the position in a string where the specified occurrence of a POSIX regular expression is located.

**Syntax:**
```sql
regexp_instr(str, regexp[, start[, N[, flags[, subexpr]]]])
```

**Example:**
```sql
SELECT regexp_instr('ABCDEF', 'C(.)(..)');
```

### String Functions

**Available functions:** `ascii`, `bit_length`, `btrim`, `character_length`, `chr`, `concat`, `concat_ws`, `contains`, `ends_with`, `find_in_set`, `initcap`, `left`, `levenshtein`, `lower`, `lpad`, `ltrim`, `octet_length`, `overlay`, `repeat`, `replace`, `reverse`, `right`, `rpad`, `rtrim`, `split_part`, `starts_with`, `strpos`, `substr`, `substr_index`, `to_hex`, `translate`, `upper`

### `ascii`

Returns the first Unicode scalar value of a string.

**Syntax:**
```sql
ascii(str)
```

**Example:**
```sql
select ascii('abc');
```

### `bit_length`

Returns the bit length of a string.

**Syntax:**
```sql
bit_length(str)
```

**Example:**
```sql
select bit_length('datafusion');
```

### `btrim`

Trims the specified trim string from the start and end of a string. If no trim string is provided, all whitespace is removed from the start and end of the input string.

**Syntax:**
```sql
btrim(str[, trim_str])
```

**Example:**
```sql
select btrim('__datafusion____', '_');
```

### `character_length`

Returns the number of characters in a string.

**Syntax:**
```sql
character_length(str)
```

**Example:**
```sql
select character_length('Ångström');
```

### `chr`

Returns a string containing the character with the specified Unicode scalar value.

**Syntax:**
```sql
chr(expression)
```

**Example:**
```sql
select chr(128640);
```

### `concat`

Concatenates multiple strings together.

**Syntax:**
```sql
concat(str[, ..., str_n])
```

**Example:**
```sql
select concat('data', 'f', 'us', 'ion');
```

### `concat_ws`

Concatenates multiple strings together with a specified separator.

**Syntax:**
```sql
concat_ws(separator, str[, ..., str_n])
```

**Example:**
```sql
select concat_ws('_', 'data', 'fusion');
```

### `contains`

Return true if search_str is found within string (case-sensitive).

**Syntax:**
```sql
contains(str, search_str)
```

**Example:**
```sql
select contains('the quick brown fox', 'row');
```

### `ends_with`

Tests if a string ends with a substring.

**Syntax:**
```sql
ends_with(str, substr)
```

**Example:**
```sql
select ends_with('datafusion', 'soin');
```

### `find_in_set`

Returns a value in the range of 1 to N if the string str is in the string list strlist consisting of N substrings.

**Syntax:**
```sql
find_in_set(str, strlist)
```

**Example:**
```sql
select find_in_set('b', 'a,b,c,d');
```

### `initcap`

Capitalizes the first character in each word in the input string. Words are delimited by non-alphanumeric characters.

**Syntax:**
```sql
initcap(str)
```

**Example:**
```sql
select initcap('apache datafusion');
```

### `left`

Returns a specified number of characters from the left side of a string.

**Syntax:**
```sql
left(str, n)
```

**Example:**
```sql
select left('datafusion', 4);
```

### `levenshtein`

Returns the [`Levenshtein distance`](https://en.wikipedia.org/wiki/Levenshtein_distance) between the two given strings.

**Syntax:**
```sql
levenshtein(str1, str2)
```

**Example:**
```sql
select levenshtein('kitten', 'sitting');
```

### `lower`

Converts a string to lower-case.

**Syntax:**
```sql
lower(str)
```

**Example:**
```sql
select lower('Ångström');
```

### `lpad`

Pads the left side of a string with another string to a specified string length.

**Syntax:**
```sql
lpad(str, n[, padding_str])
```

**Example:**
```sql
select lpad('Dolly', 10, 'hello');
```

### `ltrim`

Trims the specified trim string from the beginning of a string. If no trim string is provided, all whitespace is removed from the start of the input string.

**Syntax:**
```sql
ltrim(str[, trim_str])
```

**Example:**
```sql
select ltrim(' datafusion ');
```

### `octet_length`

Returns the length of a string in bytes.

**Syntax:**
```sql
octet_length(str)
```

**Example:**
```sql
select octet_length('Ångström');
```

### `overlay`

Returns the string which is replaced by another string from the specified position and specified count length.

**Syntax:**
```sql
overlay(str PLACING substr FROM pos [FOR count])
```

**Example:**
```sql
select overlay('Txxxxas' placing 'hom' from 2 for 4);
```

### `repeat`

Returns a string with an input string repeated a specified number.

**Syntax:**
```sql
repeat(str, n)
```

**Example:**
```sql
select repeat('data', 3);
```

### `replace`

Replaces all occurrences of a specified substring in a string with a new substring.

**Syntax:**
```sql
replace(str, substr, replacement)
```

**Example:**
```sql
select replace('ABabbaBA', 'ab', 'cd');
```

### `reverse`

Reverses the character order of a string.

**Syntax:**
```sql
reverse(str)
```

**Example:**
```sql
select reverse('datafusion');
```

### `right`

Returns a specified number of characters from the right side of a string.

**Syntax:**
```sql
right(str, n)
```

**Example:**
```sql
select right('datafusion', 6);
```

### `rpad`

Pads the right side of a string with another string to a specified string length.

**Syntax:**
```sql
rpad(str, n[, padding_str])
```

**Example:**
```sql
select rpad('datafusion', 20, '_-');
```

### `rtrim`

Trims the specified trim string from the end of a string. If no trim string is provided, all whitespace is removed from the end of the input string.

**Syntax:**
```sql
rtrim(str[, trim_str])
```

**Example:**
```sql
select rtrim(' datafusion ');
```

### `split_part`

Splits a string based on a specified delimiter and returns the substring in the specified position.

**Syntax:**
```sql
split_part(str, delimiter, pos)
```

**Example:**
```sql
select split_part('1.2.3.4.5', '.', 3);
```

### `starts_with`

Tests if a string starts with a substring.

**Syntax:**
```sql
starts_with(str, substr)
```

**Example:**
```sql
select starts_with('datafusion','data');
```

### `strpos`

Returns the starting position of a specified substring in a string. Positions begin at 1. If the substring does not exist in the string, the function returns 0.

**Syntax:**
```sql
strpos(str, substr)
```

**Example:**
```sql
select strpos('datafusion', 'fus');
```

### `substr`

Extracts a substring of a specified number of characters from a specific starting position in a string.

**Syntax:**
```sql
substr(str, start_pos[, length])
```

**Example:**
```sql
select substr('datafusion', 5, 3);
```

### `substr_index`

Returns the substring from str before count occurrences of the delimiter delim. If count is positive, everything to the left of the final delimiter (counting from the left) is returned. If count is negative, everything to the right of the final delimiter (counting from the right) is returned.

**Syntax:**
```sql
substr_index(str, delim, count)
```

**Example:**
```sql
select substr_index('www.apache.org', '.', 1);
```

### `to_hex`

Converts an integer to a hexadecimal string.

**Syntax:**
```sql
to_hex(int)
```

**Example:**
```sql
select to_hex(12345689);
```

### `translate`

Translates characters in a string to specified translation characters.

**Syntax:**
```sql
translate(str, chars, translation)
```

**Example:**
```sql
select translate('twice', 'wic', 'her');
```

### `upper`

Converts a string to upper-case.

**Syntax:**
```sql
upper(str)
```

**Example:**
```sql
select upper('dataFusion');
```

### Struct Functions

**Available functions:** `named_struct`, `struct`

### `named_struct`

Returns an Arrow struct using the specified name and input expressions pairs.

**Syntax:**
```sql
named_struct(expression1_name, expression1_input[, ..., expression_n_name, expression_n_input])
```

**Example:**
```sql
select * from t;
```

### `struct`

Returns an Arrow struct using the specified input expressions optionally named. Fields in the returned struct use the optional name or the `cN` naming convention. For example: `c0`, `c1`, `c2`, etc.

**Syntax:**
```sql
struct(expression1[, ..., expression_n])
```

**Example:**
```sql
select * from t;
```

### Time and Date Functions

**Available functions:** `current_date`, `current_time`, `date_bin`, `date_part`, `date_trunc`, `from_unixtime`, `make_date`, `make_time`, `now`, `to_char`, `to_date`, `to_local_time`, `to_time`, `to_timestamp`, `to_timestamp_micros`, `to_timestamp_millis`, `to_timestamp_nanos`, `to_timestamp_seconds`, `to_unixtime`

### `current_date`

Returns the current date in the session time zone. The `current_date()` return value is determined at query time and will return the same date, no matter when in the query plan the function executes.

**Syntax:**
```sql
current_date()
```

### `current_time`

Returns the current time in the session time zone. The `current_time()` return value is determined at query time and will return the same time, no matter when in the query plan the function executes. The session time zone can be set using the statement 'SET datafusion.execution.time_zone = desired time zone'. The time zone can be a value like +00:00, 'Europe/London' etc.

**Syntax:**
```sql
current_time()
```

### `date_bin`

Calculates time intervals and returns the start of the interval nearest to the specified timestamp. Use `date_bin` to downsample time series data by grouping rows into time-based "bins" or "windows" and applying an aggregate or selector function to each window. For example, if you "bin" or "window" data into 15 minute intervals, an input timestamp of `2023-01-01T18:18:18Z` will be updated to the start time of the 15 minute bin it is in: `2023-01-01T18:15:00Z`.

**Syntax:**
```sql
date_bin(interval, expression, origin-timestamp)
```

**Example:**
```sql
SELECT date_bin(interval '1 day', time) as bin
FROM VALUES ('2023-01-01T18:18:18Z'), ('2023-01-03T19:00:03Z') t(time);
```

### `date_part`

Returns the specified part of the date as an integer.

**Syntax:**
```sql
date_part(part, expression)
```

### `date_trunc`

Truncates a timestamp or time value to a specified precision.

**Syntax:**
```sql
date_trunc(precision, expression)
```

### `from_unixtime`

Converts an integer to RFC3339 timestamp format (`YYYY-MM-DDT00:00:00.000000000Z`). Integers and unsigned integers are interpreted as seconds since the unix epoch (`1970-01-01T00:00:00Z`) return the corresponding timestamp.

**Syntax:**
```sql
from_unixtime(expression[, timezone])
```

**Example:**
```sql
select from_unixtime(1599572549, 'America/New_York');
```

### `make_date`

Make a date from year/month/day component parts.

**Syntax:**
```sql
make_date(year, month, day)
```

**Example:**
```sql
select make_date(2023, 1, 31);
```

### `make_time`

Make a time from hour/minute/second component parts.

**Syntax:**
```sql
make_time(hour, minute, second)
```

**Example:**
```sql
select make_time(13, 23, 1);
```

### `now`

Returns the current timestamp in the system configured timezone (None by default). The `now()` return value is determined at query time and will return the same timestamp, no matter when in the query plan the function executes.

**Syntax:**
```sql
now()
```

### `to_char`

Returns a string representation of a date, time, timestamp or duration based on a [Chrono format](https://docs.rs/chrono/latest/chrono/format/strftime/index.html). Unlike the PostgreSQL equivalent of this function numerical formatting is not supported.

**Syntax:**
```sql
to_char(expression, format)
```

**Example:**
```sql
select to_char('2023-03-01'::date, '%d-%m-%Y');
```

### `to_date`

Converts a value to a date (`YYYY-MM-DD`). Supports strings, numeric and timestamp types as input. Strings are parsed as YYYY-MM-DD (e.g. '2023-07-20') if no [Chrono format](https://docs.rs/chrono/latest/chrono/format/strftime/index.html)s are provided. Integers and doubles are interpreted as days since the unix epoch (`1970-01-01T00:00:00Z`). Returns the corresponding date. Note: `to_date` returns Date32, which represents its values as the number of days since unix epoch(`1970-01-01`) stored as

**Syntax:**
```sql
to_date('2017-05-31', '%Y-%m-%d')
```

**Example:**
```sql
select to_date('2023-01-31');
```

### `to_local_time`

Converts a timestamp with a timezone to a timestamp without a timezone (with no offset or timezone information). This function handles daylight saving time changes.

**Syntax:**
```sql
to_local_time(expression)
```

**Example:**
```sql
SELECT to_local_time('2024-04-01T00:00:20Z'::timestamp);
```

### `to_time`

Converts a value to a time (`HH:MM:SS.nnnnnnnnn`). Supports strings and timestamps as input. Strings are parsed as `HH:MM:SS`, `HH:MM:SS.nnnnnnnnn`, or `HH:MM` if no [Chrono format](https://docs.rs/chrono/latest/chrono/format/strftime/index.html)s are provided. Timestamps will have the time portion extracted. Returns the corresponding time. Note: `to_time` returns Time64(Nanosecond), which represents the time of day in nanoseconds since midnight.

**Syntax:**
```sql
to_time('12:30:45', '%H:%M:%S')
```

**Example:**
```sql
select to_time('12:30:45');
```

### `to_timestamp`

Converts a value to a timestamp (`YYYY-MM-DDT00:00:00.000000<TZ>`) in the session time zone. Supports strings, integer, unsigned integer, and double types as input. Strings are parsed as RFC3339 (e.g. '2023-07-20T05:44:00') if no [Chrono formats](https://docs.rs/chrono/latest/chrono/format/strftime/index.html) are provided. Strings that parse without a time zone are treated as if they are in the session time zone, or UTC if no session time zone is set. Integers, unsigned integers, and doubles ar

**Syntax:**
```sql
to_timestamp(expression[, ..., format_n])
```

**Example:**
```sql
select to_timestamp('2023-01-31T09:26:56.123456789-05:00');
```

### `to_timestamp_micros`

Converts a value to a timestamp (`YYYY-MM-DDT00:00:00.000000<TZ>`) in the session time zone. Supports strings, integer, unsigned integer, and double types as input. Strings are parsed as RFC3339 (e.g. '2023-07-20T05:44:00') if no [Chrono formats](https://docs.rs/chrono/latest/chrono/format/strftime/index.html) are provided. Strings that parse without a time zone are treated as if they are in the session time zone, or UTC if no session time zone is set. Integers, unsigned integers, and doubles ar

**Syntax:**
```sql
to_timestamp_micros(expression[, ..., format_n])
```

**Example:**
```sql
select to_timestamp_micros('2023-01-31T09:26:56.123456789-05:00');
```

### `to_timestamp_millis`

Converts a value to a timestamp (`YYYY-MM-DDT00:00:00.000<TZ>`) in the session time zone. Supports strings, integer, unsigned integer, and double types as input. Strings are parsed as RFC3339 (e.g. '2023-07-20T05:44:00') if no [Chrono formats](https://docs.rs/chrono/latest/chrono/format/strftime/index.html) are provided. Strings that parse without a time zone are treated as if they are in the session time zone, or UTC if no session time zone is set. Integers, unsigned integers, and doubles are i

**Syntax:**
```sql
to_timestamp_millis(expression[, ..., format_n])
```

**Example:**
```sql
select to_timestamp_millis('2023-01-31T09:26:56.123456789-05:00');
```

### `to_timestamp_nanos`

Converts a value to a timestamp (`YYYY-MM-DDT00:00:00.000000000<TZ>`) in the session time zone. Supports strings, integer, unsigned integer, and double types as input. Strings are parsed as RFC3339 (e.g. '2023-07-20T05:44:00') if no [Chrono formats](https://docs.rs/chrono/latest/chrono/format/strftime/index.html) are provided. Strings that parse without a time zone are treated as if they are in the session time zone. Integers, unsigned integers, and doubles are interpreted as nanoseconds since t

**Syntax:**
```sql
to_timestamp_nanos(expression[, ..., format_n])
```

**Example:**
```sql
select to_timestamp_nanos('2023-01-31T09:26:56.123456789-05:00');
```

### `to_timestamp_seconds`

Converts a value to a timestamp (`YYYY-MM-DDT00:00:00<TZ>`) in the session time zone. Supports strings, integer, unsigned integer, and double types as input. Strings are parsed as RFC3339 (e.g. '2023-07-20T05:44:00') if no [Chrono formats](https://docs.rs/chrono/latest/chrono/format/strftime/index.html) are provided. Strings that parse without a time zone are treated as if they are in the session time zone, or UTC if no session time zone is set. Integers, unsigned integers, and doubles are inter

**Syntax:**
```sql
to_timestamp_seconds(expression[, ..., format_n])
```

**Example:**
```sql
select to_timestamp_seconds('2023-01-31T09:26:56.123456789-05:00');
```

### `to_unixtime`

Converts a value to seconds since the unix epoch (`1970-01-01T00:00:00`). Supports strings, dates, timestamps, integer, unsigned integer, and float types as input. Strings are parsed as RFC3339 (e.g. '2023-07-20T05:44:00') if no [Chrono formats](https://docs.rs/chrono/latest/chrono/format/strftime/index.html) are provided. Integers, unsigned integers, and floats are interpreted as seconds since the unix epoch (`1970-01-01T00:00:00`).

**Syntax:**
```sql
to_unixtime(expression[, ..., format_n])
```

**Example:**
```sql
select to_unixtime('2020-09-08T12:00:00+00:00');
```

### Union Functions

**Available functions:** `union_extract`, `union_tag`

### `union_extract`

Returns the value of the given field in the union when selected, or NULL otherwise.

**Syntax:**
```sql
union_extract(union, field_name)
```

**Example:**
```sql
select union_column, union_extract(union_column, 'a'), union_extract(union_column, 'b') from table_with_union;
```

### `union_tag`

Returns the name of the currently selected field in the union

**Syntax:**
```sql
union_tag(union_expression)
```

**Example:**
```sql
select union_column, union_tag(union_column) from table_with_union;
```

---

## Special Functions

### Expansion Functions

**Available functions:** `unnest`

### `unnest`

Expands an array or map into rows.

**Syntax:**
```sql
> select unnest(make_array(1, 2, 3, 4, 5)) as unnested;
```

**Example:**
```sql
select unnest(make_array(1, 2, 3, 4, 5)) as unnested;
```

---

## Subqueries

### FROM clause subqueries

**Available functions:** `example`

### `example`

The following query returns the average of maximum values per room. The inner query returns the maximum value for each field from each room. The outer query uses the results of the inner query and returns the average maximum value for each field.

**Syntax:**
```sql
SELECT
```

### HAVING clause subqueries

**Available functions:** `examples`

### `examples`

The following query calculates the averages of even and odd numbers in table `y` and returns the averages that are equal to the maximum value of `column_1` in table `x`.

**Syntax:**
```sql
SELECT
```

### SELECT clause subqueries

**Available functions:** `example`

### `example`

```sql SELECT column_1, ( SELECT first_value(string) FROM y WHERE number = x.column_1 ) AS "numeric string" FROM x; +----------+----------------+ | column_1 | numeric string | +----------+----------------+ | 1 | one | | 2 | two | +----------+----------------+ ```

**Syntax:**
```sql
SELECT
```

---

## Window Functions

### Analytical Functions

**Available functions:** `first_value`, `lag`, `last_value`, `lead`, `nth_value`

### `first_value`

Returns value evaluated at the row that is the first row of the window frame.

**Syntax:**
```sql
first_value(expression)
```

**Example:**
```sql
SELECT department,
 employee_id,
 salary,
 first_value(salary) OVER (PARTITION BY department ORDER BY salary DESC) AS top_salary
FROM employees;
```

### `lag`

Returns value evaluated at the row that is offset rows before the current row within the partition; if there is no such row, instead return default (which must be of the same type as value).

**Syntax:**
```sql
lag(expression, offset, default)
```

**Example:**
```sql
SELECT employee_id,
 salary,
 lag(salary, 1, 0) OVER (ORDER BY employee_id) AS prev_salary
FROM employees;
```

### `last_value`

Returns value evaluated at the row that is the last row of the window frame.

**Syntax:**
```sql
last_value(expression)
```

**Example:**
```sql
SELECT department,
 employee_id,
 salary,
 last_value(salary) OVER (PARTITION BY department ORDER BY salary) AS running_last_salary
FROM employees;
```

### `lead`

Returns value evaluated at the row that is offset rows after the current row within the partition; if there is no such row, instead return default (which must be of the same type as value).

**Syntax:**
```sql
lead(expression, offset, default)
```

**Example:**
```sql
SELECT
 employee_id,
 department,
 salary,
 lead(salary, 1, 0) OVER (PARTITION BY department ORDER BY salary) AS next_salary
FROM employees;
```

### `nth_value`

Returns the value evaluated at the nth row of the window frame (counting from 1). Returns NULL if no such row exists.

**Syntax:**
```sql
nth_value(expression, n)
```

**Example:**
```sql
SELECT nth_value(salary, 2) OVER (
 ORDER BY salary
 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) AS nth_value
FROM employees;
```

### Ranking Functions

**Available functions:** `cume_dist`, `dense_rank`, `ntile`, `percent_rank`, `rank`, `row_number`

### `cume_dist`

Relative rank of the current row: (number of rows preceding or peer with the current row) / (total rows).

**Syntax:**
```sql
cume_dist()
```

**Example:**
```sql
SELECT salary,
 cume_dist() OVER (ORDER BY salary) AS cume_dist
FROM employees;
```

### `dense_rank`

Returns the rank of the current row without gaps. This function ranks rows in a dense manner, meaning consecutive ranks are assigned even for identical values.

**Syntax:**
```sql
dense_rank()
```

**Example:**
```sql
SELECT department,
 salary,
 dense_rank() OVER (PARTITION BY department ORDER BY salary DESC) AS dense_rank
FROM employees;
```

### `ntile`

Integer ranging from 1 to the argument value, dividing the partition as equally as possible

**Syntax:**
```sql
ntile(expression)
```

**Example:**
```sql
SELECT employee_id,
 salary,
 ntile(4) OVER (ORDER BY salary DESC) AS quartile
FROM employees;
```

### `percent_rank`

Returns the percentage rank of the current row within its partition. The value ranges from 0 to 1 and is computed as `(rank - 1) / (total_rows - 1)`.

**Syntax:**
```sql
percent_rank()
```

**Example:**
```sql
SELECT employee_id,
 salary,
 percent_rank() OVER (ORDER BY salary) AS percent_rank
FROM employees;
```

### `rank`

Returns the rank of the current row within its partition, allowing gaps between ranks. This function provides a ranking similar to `row_number`, but skips ranks for identical values.

**Syntax:**
```sql
rank()
```

**Example:**
```sql
SELECT department,
 salary,
 rank() OVER (PARTITION BY department ORDER BY salary DESC) AS rank
FROM employees;
```

### `row_number`

Number of the current row within its partition, counting from 1.

**Syntax:**
```sql
row_number()
```

**Example:**
```sql
SELECT department,
 salary,
 row_number() OVER (PARTITION BY department ORDER BY salary DESC) AS row_num
FROM employees;
```

---

## Document Metadata

- **Total Functions:** 223
- **Source:** [Apache DataFusion Documentation](https://datafusion.apache.org/user-guide/sql/)
- **Note:** This is an auto-generated reference. For the most up-to-date
  information, consult the official DataFusion documentation.
