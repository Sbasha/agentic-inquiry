module Complex (distance, rootMeanSquare) where

distance :: Double -> Double -> Double
distance a b = abs (a - b)

rootMeanSquare :: [Double] -> Double
rootMeanSquare [] = 0
rootMeanSquare values = sqrt (sum (map (^2) values) / fromIntegral (length values))
