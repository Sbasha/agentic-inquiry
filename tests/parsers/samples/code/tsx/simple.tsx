import React from "react";
import { ComplexPreview, useComplexMetrics } from "./complex";

export const SimplePanel: React.FC = () => {
    const metrics = useComplexMetrics([1, 2, 3]);
    return (
        <div>
            <ComplexPreview values={[10, 5]} />
            <p>{`baseline=${metrics.distance}, rms=${metrics.rms.toFixed(2)}`}</p>
        </div>
    );
};
