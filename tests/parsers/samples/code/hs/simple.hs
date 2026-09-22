module Simple (summarize) where

import Complex

summarize :: String
summarize =
    let
        baseline = distance 10 3
        rms = rootMeanSquare [1, 2, 3]
    in
    "baseline=" ++ show baseline ++ ", rms=" ++ show rms
