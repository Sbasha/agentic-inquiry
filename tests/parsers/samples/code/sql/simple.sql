-- Uses functions defined in complex.sql
WITH metrics AS (
    SELECT
        complex_distance(10, 3) AS baseline,
        complex_rms(ARRAY[1, 2, 3]) AS rms
)
SELECT * FROM metrics;
