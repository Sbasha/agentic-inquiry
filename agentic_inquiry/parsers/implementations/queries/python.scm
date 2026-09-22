; Python tree-sitter queries for extracting code symbols and relationships

; Method definitions (functions inside classes)
(class_definition
  body: (block
    (function_definition
      name: (identifier) @code_method.name
      parameters: (parameters) @code_method.params
      body: (block) @code_method.body
    ) @code_method.def
  )
)

; Function definitions
(function_definition
  name: (identifier) @code_function.name
  parameters: (parameters) @code_function.params
  body: (block) @code_function.body
) @code_function.def

; Class definitions
(class_definition
  name: (identifier) @code_class.name
  superclasses: (argument_list)? @code_class.bases
  body: (block) @code_class.body
) @code_class.def

; Import statements
(import_statement
  name: (dotted_name) @import.module
) @import

(import_from_statement
  module_name: (dotted_name) @import.module
  name: (dotted_name)? @import.name
) @import.from

; Function calls - simple function calls like foo()
(call
  function: (identifier) @call.function
) @call

; Method calls - any attribute call like obj.method(), self.db.execute(), get().method()
; Use (_) wildcard for object to capture all patterns:
; - self.method() (object is identifier)
; - self.db.method() (object is attribute)
; - get_obj().method() (object is call)
; - items[0].method() (object is subscript)
(call
  function: (attribute
    object: (_) @call.object
    attribute: (identifier) @call.method
  )
) @call.method

; Variable assignments
(assignment
  left: (identifier) @code_variable.name
  right: (_) @code_variable.value
) @assignment

; Decorators
(decorated_definition
  (decorator) @code_decorator
  definition: (_) @decorated.target
)

; Comments and docstrings
(comment) @comment

(expression_statement
  (string) @docstring
)
