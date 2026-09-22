public with sharing class DynamicExecutor {
    public static Object run(String methodName) {
        Type simple = Type.forName('SimpleService');
        if (simple == null) {
            throw new TypeException('SimpleService not found');
        }
        return simple.getMethod(methodName).invoke(null);
    }
}
