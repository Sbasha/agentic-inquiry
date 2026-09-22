module Simple exposing (summarize)

import Complex


summarize : String
summarize =
    let
        metrics =
            Complex.analyzeMetrics [ 1, 2, 3 ]
    in
    "baseline=" ++ String.fromFloat metrics.distance ++ ", rms=" ++ String.fromFloat metrics.rms
