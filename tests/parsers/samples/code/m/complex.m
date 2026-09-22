classdef ComplexMetrics
    methods (Static)
        function result = distance(a, b)
            result = abs(a - b);
        end

        function result = rootMeanSquare(values)
            if isempty(values)
                result = 0;
                return;
            end
            squares = values .^ 2;
            result = sqrt(sum(squares) / numel(values));
        end
    end
end
