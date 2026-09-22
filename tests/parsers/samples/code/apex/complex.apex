public with sharing class ComplexController {
    public static Decimal normalizeScore(List<Integer> values) {
        if (values == null || values.isEmpty()) {
            return 0;
        }
        Integer total = 0;
        for (Integer value : values) {
            total += value * value;
        }
        Decimal average = Math.sqrt(total) / values.size();
        return average.setScale(2);
    }

    public static Decimal distance(Integer a, Integer b) {
        return Math.abs(a - b);
    }
}
