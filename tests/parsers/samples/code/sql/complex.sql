CREATE OR REPLACE FUNCTION complex_distance(a INTEGER, b INTEGER)
RETURNS INTEGER AS $$
BEGIN
    RETURN ABS(a - b);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION complex_rms(values INTEGER[])
RETURNS DOUBLE PRECISION AS $$
DECLARE
    total DOUBLE PRECISION := 0;
    value INTEGER;
BEGIN
    IF array_length(values, 1) IS NULL THEN
        RETURN 0;
    END IF;
    FOREACH value IN ARRAY values LOOP
        total := total + value * value;
    END LOOP;
    RETURN sqrt(total / array_length(values, 1));
END;
$$ LANGUAGE plpgsql;
