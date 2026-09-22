import type { FC } from "react";
import { useMemo } from "react";

export function useComplexMetrics(values: number[]): { distance: number; rms: number } {
    return useMemo(() => {
        if (values.length === 0) {
            return { distance: 0, rms: 0 };
        }
        const distance = Math.abs(values[0] - values[values.length - 1]);
        const total = values.reduce((acc, value) => acc + value * value, 0);
        return { distance, rms: Math.sqrt(total / values.length) };
    }, [values]);
}

export const ComplexPreview: FC<{ values: number[] }> = ({ values }) => {
    const metrics = useComplexMetrics(values);
    return <span>{`preview:${metrics.distance}:${metrics.rms.toFixed(2)}`}</span>;
};
