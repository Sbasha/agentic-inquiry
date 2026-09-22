; Apex tree-sitter queries for extracting code symbols and relationships
; Salesforce Apex (tree-sitter-sfapex via tree-sitter-language-pack)

; Classes (top-level and inner)
(class_declaration
  name: (identifier) @code_class.name
  superclass: (superclass)? @code_class.bases
  interfaces: (interfaces)? @code_class.bases
  body: (class_body) @code_class.body) @code_class.def

; Triggers are named top-level containers; reuse the class chunk path
(trigger_declaration
  name: (identifier) @code_class.name
  body: (trigger_body) @code_class.body) @code_class.def

; Interfaces
(interface_declaration
  name: (identifier) @code_interface.name
  body: (interface_body) @code_interface.body) @code_interface.def

; Enums
(enum_declaration
  name: (identifier) @code_enum.name
  body: (enum_body) @code_enum.body) @code_enum.def

; Methods (interface methods may have no body)
(method_declaration
  name: (identifier) @code_method.name) @code_method.def

; Constructors
(constructor_declaration
  name: (identifier) @code_method.name
  parameters: (formal_parameters) @code_method.params
  body: (constructor_body) @code_method.body) @code_method.def

; Fields and properties (property = field_declaration with accessor_list)
(field_declaration
  declarator: (variable_declarator
    name: (identifier) @code_property.name)) @code_property.def

; Method invocations
(method_invocation
  object: (_)? @call.object
  name: (identifier) @call.method
  arguments: (argument_list) @call.args) @call

; Comments
(line_comment) @comment
(block_comment) @comment
