public class DynamicExample {
    public static Object run(String methodName) {
        try {
            java.lang.reflect.Method method = SimpleExample.class.getMethod(methodName);
            return method.invoke(new SimpleExample());
        } catch (ReflectiveOperationException ex) {
            return "unknown";
        }
    }
}
