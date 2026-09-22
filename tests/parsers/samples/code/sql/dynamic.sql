-- Executes the simple query dynamically for cross-file linking
DO $$
DECLARE
    result RECORD;
BEGIN
    FOR result IN EXECUTE $query$
        WITH metrics AS (
            SELECT
                complex_distance(10, 3) AS baseline,
                complex_rms(ARRAY[1, 2, 3]) AS rms
        )
        SELECT 'dynamic:' || baseline || ':' || rms AS summary FROM metrics
    $query$ LOOP
        RAISE NOTICE '%', result.summary;
    END LOOP;
END;
$$;
