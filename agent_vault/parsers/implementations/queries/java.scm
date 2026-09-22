; Java tree-sitter queries for extracting code symbols and relationships

; Method declarations
(method_declaration
  name: (identifier) @code_method.name
  parameters: (formal_parameters) @code_method.params
  body: (block) @code_method.body
) @code_method.def

; Class declarations
(class_declaration
  name: (identifier) @code_class.name
  body: (class_body) @code_class.body
) @code_class.def

; Interface declarations
(interface_declaration
  name: (identifier) @code_interface.name
  body: (interface_body) @code_interface.body
) @code_interface.def

; Constructor declarations
(constructor_declaration
  name: (identifier) @code_method.name
  parameters: (formal_parameters) @code_method.params
  body: (constructor_body) @code_method.body
) @code_method.def

; Import declarations
(import_declaration
  (scoped_identifier) @import.module
) @import

; Package declaration
(package_declaration) @package

; Method invocations - capture object for chained calls
; Handles obj.method(), this.method(), getObj().method(), etc.
(method_invocation
  object: (_)? @call.object
  name: (identifier) @call.method
  arguments: (argument_list) @call.args
) @call

; Field declarations
(field_declaration
  declarator: (variable_declarator
    name: (identifier) @code_property.name
  )
) @code_property

; Comments
(line_comment) @comment
(block_comment) @comment
