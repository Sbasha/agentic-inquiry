import React from "react";

export function useComplexMetrics(values) {
    return React.useMemo(() => {
        if (!values.length) {
            return { distance: 0, rms: 0 };
        }
        const baseline = Math.abs(values[0] - values[values.length - 1]);
        const total = values.reduce((acc, value) => acc + value * value, 0);
        return {
            distance: baseline,
            rms: Math.sqrt(total / values.length),
        };
    }, [values]);
}

export const ComplexPreview = ({ values }) => {
    const metrics = useComplexMetrics(values);
    return <span>{`preview:${metrics.distance}:${metrics.rms.toFixed(2)}`}</span>;
};
