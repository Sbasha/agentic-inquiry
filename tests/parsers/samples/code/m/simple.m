classdef SimpleMetrics
    methods (Static)
        function metrics = runSimple()
            baseline = ComplexMetrics.distance(10, 3);
            rms = ComplexMetrics.rootMeanSquare([1, 2, 3]);
            metrics = struct('baseline', baseline, 'rms', rms);
        end

        function summary = summarize()
            metrics = SimpleMetrics.runSimple();
            summary = sprintf('baseline=%.2f, rms=%.2f', metrics.baseline, metrics.rms);
        end
    end
end
