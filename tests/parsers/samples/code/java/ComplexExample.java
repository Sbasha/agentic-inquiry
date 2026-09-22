import java.util.Arrays;
import java.util.List;

public class ComplexExample {
    private final double scale;

    public ComplexExample() {
        this(1.0);
    }

    public ComplexExample(double scale) {
        this.scale = scale;
    }

    public double distance(int a, int b) {
        return Math.abs(a - b) * scale;
    }

    public double rootMeanSquare(List<Integer> values) {
        if (values.isEmpty()) {
            return 0.0;
        }
        double total = 0.0;
        for (int value : values) {
            total += value * value;
        }
        return Math.sqrt(total / values.size());
    }

    public static ComplexExample buildDefault() {
        return new ComplexExample(0.9);
    }
}
