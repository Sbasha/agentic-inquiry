module Complex exposing (analyzeMetrics, distance)

distance : Float -> Float -> Float
distance a b =
    abs (a - b)

analyzeMetrics : List Float -> { distance : Float, rms : Float }
analyzeMetrics values =
    let
        baseline =
            case values of
                [] ->
                    0

                first :: rest ->
                    let
                        lastValue =
                            case List.reverse values of
                                [] ->
                                    first

                                lfirst :: _ ->
                                    lfirst
                    in
                    distance first lastValue

        squares =
            values |> List.map (\v -> v * v)

        rms =
            case List.length values of
                0 ->
                    0

                len ->
                    (List.sum squares / toFloat len) |> sqrt
    in
    { distance = baseline, rms = rms }
