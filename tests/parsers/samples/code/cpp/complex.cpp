#include <cmath>
#include <vector>

class ComplexAnalyzer {
public:
    explicit ComplexAnalyzer(double scale = 1.0) : scale_(scale) {}

    double distance(int a, int b) const {
        return std::abs(a - b) * scale_;
    }

    double root_mean_square(const std::vector<double>& values) const {
        if (values.empty()) {
            return 0.0;
        }
        double total = 0.0;
        for (double value : values) {
            total += value * value;
        }
        return std::sqrt(total / values.size());
    }

private:
    double scale_;
};

inline ComplexAnalyzer build_default_analyzer() {
    return ComplexAnalyzer(0.8);
}
