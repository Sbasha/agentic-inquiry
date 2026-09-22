"""Tests for :class:`JavaSpringDIRecognizer`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_inquiry.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)
from agentic_inquiry.parsers.recognizers.java_spring_di import (
    JavaSpringDIRecognizer,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_java(tmp_path: Path, source: str, name: str = "App.java") -> Path:
    file_path = tmp_path / name
    file_path.write_text(source)
    return file_path


def _grouped_doc(
    file_path: Path,
    classes: dict[str, tuple[int, list[tuple[str, str, int]]]],
) -> ParsedDocument:
    """Build one chunk per class, with class members in ``symbol_metadata``.

    ``classes`` maps class_name → (class_start_line, members) where
    each member is ``(name, type, start_line)``. Mirrors what
    ``unified_code`` produces for a typical Spring file.
    """
    chunks = []
    for class_name, (class_line, members) in classes.items():
        symbol_metadata: dict[str, dict[str, int | str]] = {
            class_name: {
                "type": "class",
                "start_line": class_line,
                "end_line": class_line + 100,
            }
        }
        for mname, mtype, mline in members:
            symbol_metadata[mname] = {
                "type": mtype,
                "start_line": mline,
                "end_line": mline + 1,
            }
        chunks.append(
            ParserChunk(
                content=f"class {class_name} {{...}}",
                element_type="class",
                element_name=class_name,
                line_start=class_line,
                line_end=class_line + 100,
                symbols=[class_name, *(m[0] for m in members)],
                symbol_metadata=symbol_metadata,
            )
        )
    return ParsedDocument(
        doc_id=str(file_path),
        file_path=str(file_path),
        chunks=chunks,
        metadata={},
    )


def _beans(chunk: ParserChunk) -> list[ParserRelationship]:
    return [r for r in chunk.relationships if r.type == "spring_di_bean"]


def _deps(chunk: ParserChunk) -> list[ParserRelationship]:
    return [r for r in chunk.relationships if r.type == "spring_di_depends_on"]


def _all_beans(doc: ParsedDocument) -> list[ParserRelationship]:
    return [
        r for c in doc.chunks for r in c.relationships if r.type == "spring_di_bean"
    ]


def _all_deps(doc: ParsedDocument) -> list[ParserRelationship]:
    return [
        r
        for c in doc.chunks
        for r in c.relationships
        if r.type == "spring_di_depends_on"
    ]


# ---------------------------------------------------------------------------
# Bean providers
# ---------------------------------------------------------------------------


class TestBeanProviders:
    async def test_all_class_stereotypes_recognised(self, tmp_path):
        """Each of the six class-level stereotypes produces a
        ``spring_di_bean`` edge with the appropriate stereotype
        metadata and a default decapitalised bean name.
        """
        src = """package com.example;
import org.springframework.stereotype.Service;
import org.springframework.stereotype.Component;
import org.springframework.stereotype.Repository;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.context.annotation.Configuration;

@Service
public class FooService {}

@Component
public class FooComponent {}

@Repository
public class FooRepository {}

@Controller
public class FooController {}

@RestController
public class FooRestController {}

@Configuration
public class FooConfig {}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            {
                "FooService": (9, []),
                "FooComponent": (12, []),
                "FooRepository": (15, []),
                "FooController": (18, []),
                "FooRestController": (21, []),
                "FooConfig": (24, []),
            },
        )

        await JavaSpringDIRecognizer().enrich(doc)
        beans = _all_beans(doc)
        stereotypes = {r.source_name: r.metadata["stereotype"] for r in beans}
        assert stereotypes == {
            "FooService": "Service",
            "FooComponent": "Component",
            "FooRepository": "Repository",
            "FooController": "Controller",
            "FooRestController": "RestController",
            "FooConfig": "Configuration",
        }
        # Default bean name is decapitalised class name.
        bean_names = {r.source_name: r.metadata["bean_name"] for r in beans}
        assert bean_names["FooService"] == "fooService"
        # All stereotype beans are class_stereotype kind.
        assert all(r.metadata["kind"] == "class_stereotype" for r in beans)

    async def test_custom_bean_name_from_stereotype_argument(self, tmp_path):
        """``@Service("customName")`` overrides the default bean
        name. Same shape as Spring's own behaviour.
        """
        src = """package com.example;
import org.springframework.stereotype.Service;

@Service("customUserService")
public class UserService {}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (4, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        beans = _all_beans(doc)
        assert len(beans) == 1
        assert beans[0].metadata["bean_name"] == "customUserService"

    async def test_bean_method_provides_return_type(self, tmp_path):
        """``@Bean`` method produces a ``spring_di_bean`` edge whose
        source is the method, target is the return type, and
        ``kind == "bean_method"``.
        """
        src = """package com.example;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppConfig {
    @Bean
    public UserRepository userRepository() { return null; }

    @Bean("customRepo")
    public OrderRepository orderRepository() { return null; }
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            {
                "AppConfig": (
                    5,
                    [
                        ("userRepository", "method", 7),
                        ("orderRepository", "method", 10),
                    ],
                )
            },
        )

        await JavaSpringDIRecognizer().enrich(doc)
        beans = _all_beans(doc)
        # One for the @Configuration class itself plus one per @Bean method.
        by_source = {r.source_name: r for r in beans}

        assert "AppConfig" in by_source
        assert by_source["AppConfig"].metadata["kind"] == "class_stereotype"

        assert "userRepository" in by_source
        assert by_source["userRepository"].metadata["kind"] == "bean_method"
        assert by_source["userRepository"].metadata["stereotype"] == "Bean"
        assert by_source["userRepository"].target_name == "UserRepository"
        assert by_source["userRepository"].metadata["bean_name"] == "userRepository"

        assert by_source["orderRepository"].metadata["bean_name"] == "customRepo"
        assert by_source["orderRepository"].target_name == "OrderRepository"

    async def test_bean_method_return_type_stripped_of_generics(self, tmp_path):
        """``@Bean public List<User> users()`` — the bean's target
        type strips parametrization to the raw outer type
        (``List``), matching how the ``depends_on`` side handles
        the same shape. Without this, a consumer depending on
        ``List<User>`` (stored as ``List``) wouldn't match the
        factory's target (``List<User>`` unstripped).
        """
        src = """package com.example;
import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppConfig {
    @Bean
    public List<User> users() { return null; }
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            {"AppConfig": (6, [("users", "method", 8)])},
        )

        await JavaSpringDIRecognizer().enrich(doc)
        beans = _all_beans(doc)
        users_bean = next(b for b in beans if b.source_name == "users")
        assert users_bean.target_name == "List"

    async def test_bean_method_in_non_spring_class_ignored(self, tmp_path):
        """Spring silently ignores ``@Bean`` methods on plain POJOs.
        Emitting edges for those beans would claim registrations
        that don't exist in the container — misleading downstream.
        """
        src = """package com.example;
import org.springframework.context.annotation.Bean;

public class NotAConfig {
    @Bean
    public UserRepository userRepository() { return null; }
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            {"NotAConfig": (4, [("userRepository", "method", 5)])},
        )

        await JavaSpringDIRecognizer().enrich(doc)
        assert _all_beans(doc) == []
        assert _all_deps(doc) == []

    async def test_bean_method_params_become_method_scoped_deps(self, tmp_path):
        """``@Bean public Foo foo(Bar bar)`` — Bar is a dependency
        of the factory METHOD, not the enclosing class. The edge's
        ``source_type`` is ``method`` and ``source_name`` is the
        factory method name; ``injection_type`` is
        ``bean_method_param``. Primitives still filter out.
        """
        src = """package com.example;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppConfig {
    @Bean
    public UserService userService(UserRepository repo, int timeout) {
        return null;
    }
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            {"AppConfig": (5, [("userService", "method", 7)])},
        )

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)

        # Only the non-primitive dep; ``int`` filters out.
        assert len(deps) == 1
        dep = deps[0]
        assert dep.source_type == "method"
        assert dep.source_name == "userService"
        assert dep.target_name == "UserRepository"
        assert dep.metadata["injection_type"] == "bean_method_param"
        assert dep.metadata["parameter_name"] == "repo"

    async def test_qualified_stereotype_name_resolves(self, tmp_path):
        """Fully-qualified annotation names
        (``@org.springframework.stereotype.Service``) resolve the
        same as the bare form.
        """
        src = """package com.example;

@org.springframework.stereotype.Service
public class QualifiedService {}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"QualifiedService": (3, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        beans = _all_beans(doc)
        assert len(beans) == 1
        assert beans[0].metadata["stereotype"] == "Service"


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


class TestConstructorInjection:
    async def test_constructor_params_become_dependencies(self, tmp_path):
        """Every non-primitive parameter of a Spring class's
        constructor becomes a ``spring_di_depends_on`` edge.
        Covers both the modern single-ctor implicit form (no
        ``@Autowired`` needed) and the explicit form.
        """
        src = """package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    private final UserRepository repo;
    private final EmailSender sender;

    public UserService(UserRepository repo, EmailSender sender) {
        this.repo = repo;
        this.sender = sender;
    }
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (6, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        by_target = {r.target_name: r for r in deps}

        assert set(by_target) == {"UserRepository", "EmailSender"}
        for rel in deps:
            assert rel.metadata["injection_type"] == "constructor"
            assert rel.source_name == "UserService"
            assert rel.metadata["framework"] == "spring"

    async def test_primitive_params_filtered_out(self, tmp_path):
        """Primitive constructor params (``int``, ``long`` etc.) can't
        be Spring beans and must not emit ``depends_on`` edges.
        """
        src = """package com.example;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    public UserService(UserRepository repo, int count, long timeout) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (4, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        targets = {r.target_name for r in deps}
        assert targets == {"UserRepository"}

    async def test_primitive_array_param_filtered_after_normalisation(self, tmp_path):
        """``int[]`` as a constructor param must be filtered. The raw
        text ``"int[]"`` doesn't match the primitive set (the set
        contains ``"int"``, no suffix), but after stripping the
        array brackets the result is ``"int"`` — and that would
        emit a nonsense ``depends_on int`` edge if we don't
        normalise BEFORE the primitive check.
        """
        src = """package com.example;
import org.springframework.stereotype.Service;

@Service
public class Stats {
    public Stats(UserRepository repo, int[] counts, long[] timings) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"Stats": (4, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        targets = {r.target_name for r in _all_deps(doc)}
        # Only the real type. ``int[]`` and ``long[]`` filtered.
        assert targets == {"UserRepository"}

    async def test_qualifier_on_parameter_captured(self, tmp_path):
        """``@Qualifier("name")`` on a constructor param is captured
        in the dep metadata for downstream bean-name resolution.
        """
        src = """package com.example;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    public UserService(@Qualifier("smtp") EmailSender sender) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (5, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        assert len(deps) == 1
        assert deps[0].metadata["qualifier"] == "smtp"

    async def test_qualified_type_stripped_to_last_segment(self, tmp_path):
        """Package-qualified parameter types like
        ``com.example.repo.UserRepository`` must reduce to the bare
        class name ``UserRepository`` so downstream graph joins
        against unqualified symbol names actually resolve. Same
        treatment for field injection, setter injection, and
        ``@Bean`` return types — all pass through the same
        normalisation.
        """
        src = """package com.example;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    public UserService(com.example.repo.UserRepository repo,
                       com.example.mail.EmailSender sender) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (4, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        targets = {r.target_name for r in _all_deps(doc)}
        assert targets == {"UserRepository", "EmailSender"}

    async def test_generic_type_stripped_to_outer(self, tmp_path):
        """``Optional<Cache>`` collapses to the raw outer type
        ``Optional``. Documented MVP limitation: we don't unwrap
        the parametrisation.
        """
        src = """package com.example;
import java.util.Optional;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    public UserService(Optional<Cache> cache) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (5, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        assert len(deps) == 1
        assert deps[0].target_name == "Optional"


class TestFieldInjection:
    async def test_autowired_field_becomes_dependency(self, tmp_path):
        """``@Autowired`` on a field emits a ``field`` injection edge."""
        src = """package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    @Autowired
    private UserRepository repo;
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (5, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        assert len(deps) == 1
        assert deps[0].target_name == "UserRepository"
        assert deps[0].metadata["injection_type"] == "field"
        assert deps[0].metadata["parameter_name"] == "repo"

    async def test_jsr330_inject_also_recognised(self, tmp_path):
        """``@Inject`` (JSR-330) is equivalent to ``@Autowired`` for
        Spring's purposes and must produce the same edge.
        """
        src = """package com.example;
import javax.inject.Inject;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    @Inject
    private UserRepository repo;
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (5, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        assert len(deps) == 1
        assert deps[0].target_name == "UserRepository"

    async def test_primitive_array_field_filtered_after_normalisation(self, tmp_path):
        """Field injection has the same ``int[]``-as-primitive issue
        as constructor params — strip-then-check is the right order.
        """
        src = """package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class Stats {
    @Autowired
    private int[] counters;
    @Autowired
    private UserRepository repo;
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"Stats": (5, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        targets = {r.target_name for r in _all_deps(doc)}
        assert targets == {"UserRepository"}

    async def test_non_autowired_fields_ignored(self, tmp_path):
        """Fields without any injection annotation are just data and
        must not emit edges — most Spring service classes have
        private helper fields alongside injected ones.
        """
        src = """package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    @Autowired
    private UserRepository repo;
    private int cacheSize = 100;
    private final String name = "users";
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (5, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        targets = {r.target_name for r in deps}
        assert targets == {"UserRepository"}


class TestSetterInjection:
    async def test_autowired_setter_params_become_dependencies(self, tmp_path):
        """Methods annotated ``@Autowired`` with parameters emit
        ``setter`` injection edges per param.
        """
        src = """package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    @Autowired
    public void setRepositories(UserRepository repo, OrderRepository orders) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (5, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        targets = {r.target_name: r for r in deps}
        assert set(targets) == {"UserRepository", "OrderRepository"}
        for rel in deps:
            assert rel.metadata["injection_type"] == "setter"

    async def test_non_autowired_method_not_treated_as_setter(self, tmp_path):
        """Methods without the injection annotation aren't
        injection points, even if they look like setters.
        """
        src = """package com.example;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    public void setCacheSize(int size) {}
    public void setRepository(UserRepository repo) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (4, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        deps = _all_deps(doc)
        assert deps == []


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    async def test_plain_pojo_produces_no_edges(self, tmp_path):
        """A class with no Spring stereotype produces neither bean
        nor dependency edges even if its constructor takes what
        would look like injectable types.
        """
        src = """package com.example;

public class UserService {
    public UserService(UserRepository repo) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (3, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        assert _all_beans(doc) == []
        assert _all_deps(doc) == []

    async def test_missing_file_returns_doc_unchanged(self, tmp_path):
        missing = tmp_path / "gone.java"
        doc = _grouped_doc(missing, {"Missing": (1, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        assert _all_beans(doc) == []
        assert _all_deps(doc) == []


# ---------------------------------------------------------------------------
# Pre-filter
# ---------------------------------------------------------------------------


class TestFastPreFilter:
    async def test_wrapper_controller_still_triggers_parse(self, tmp_path):
        """A file that uses ``@Controller`` (or ``@RestController`` /
        ``@Configuration``) via a wrapper package — so neither
        ``springframework`` nor an ``@nestjs/``-style import path
        appears literally — must still trigger a parse. Without
        all supported stereotypes in the pre-filter marker list,
        a file like this would be skipped and emit zero edges.
        """
        src = """package com.example;
import com.wrapper.Controller;

@Controller
public class PageController {
    public PageController(PageService svc) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"PageController": (4, [])})

        await JavaSpringDIRecognizer().enrich(doc)
        beans = _all_beans(doc)
        deps = _all_deps(doc)
        assert len(beans) == 1
        assert beans[0].metadata["stereotype"] == "Controller"
        assert {r.target_name for r in deps} == {"PageService"}

    async def test_non_spring_file_skips_tree_sitter_parse(self, tmp_path, monkeypatch):
        src = """package com.example;

public class PlainPojo {
    private String name;
    public String getName() { return name; }
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"PlainPojo": (3, [])})

        recognizer = JavaSpringDIRecognizer()
        sentinel = type(
            "ExplodeOnParse",
            (),
            {
                "parse": lambda self, src: (_ for _ in ()).throw(
                    AssertionError("should not parse")
                )
            },
        )()
        monkeypatch.setattr(recognizer, "_parser", sentinel)

        await recognizer.enrich(doc)
        assert _all_beans(doc) == []
        assert _all_deps(doc) == []


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


class TestAttachmentAmbiguity:
    """When multiple chunks could receive an edge (ambiguous name,
    no matching line), the recognizer must refuse to guess rather
    than smear the edge onto ``code_full`` where it would collide
    with unrelated symbols. Dropping an edge is strictly better
    than misattributing it.
    """

    async def test_ambiguous_name_does_not_fall_through_to_code_full(self, tmp_path):
        src = """package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    @Autowired
    private UserRepository repo;
}
"""
        file_path = _write_java(tmp_path, src)

        # Two chunks both claim ``UserService`` with DIFFERENT
        # line_starts, and neither matches the AST's actual class
        # line (forcing name-only fallback). Third chunk is the
        # whole-file ``code_full`` sentinel — it must NOT receive
        # the edge just because the name-only tier was ambiguous.
        chunks = [
            ParserChunk(
                content="stale a",
                element_type="class",
                element_name="UserService",
                line_start=99,
                line_end=100,
                symbols=["UserService"],
                symbol_metadata={
                    "UserService": {
                        "type": "class",
                        "start_line": 99,
                        "end_line": 100,
                    }
                },
            ),
            ParserChunk(
                content="stale b",
                element_type="class",
                element_name="UserService",
                line_start=200,
                line_end=201,
                symbols=["UserService"],
                symbol_metadata={
                    "UserService": {
                        "type": "class",
                        "start_line": 200,
                        "end_line": 201,
                    }
                },
            ),
            ParserChunk(
                content="whole file",
                element_type="code_full",
                element_name="",
                line_start=-1,
                line_end=-1,
                symbols=["UserService"],
                symbol_metadata={
                    "UserService": {
                        "type": "class",
                        "start_line": 5,
                        "end_line": 8,
                    }
                },
            ),
        ]
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=chunks,
            metadata={},
        )

        await JavaSpringDIRecognizer().enrich(doc)

        # No chunk receives the edge — ambiguous name-only match +
        # no (name, line) primary hit. Dropping beats misattribution.
        for chunk in doc.chunks:
            assert _deps(chunk) == []
            assert _beans(chunk) == []


class TestIdempotence:
    async def test_second_enrich_does_not_duplicate_edges(self, tmp_path):
        src = """package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    @Autowired
    private UserRepository repo;

    public UserService(EmailSender sender) {}
}
"""
        file_path = _write_java(tmp_path, src)
        doc = _grouped_doc(file_path, {"UserService": (5, [])})

        recognizer = JavaSpringDIRecognizer()
        await recognizer.enrich(doc)
        await recognizer.enrich(doc)

        beans = _all_beans(doc)
        deps = _all_deps(doc)
        # One bean (the @Service class) + two deps (one field, one
        # constructor param) — none doubled.
        assert len(beans) == 1
        assert len(deps) == 2


# ---------------------------------------------------------------------------
# End-to-end through real ParserChain
# ---------------------------------------------------------------------------


class TestEndToEndThroughParserChain:
    async def test_spring_di_file_parsed_through_chain_gets_edges(self, tmp_path):
        src = """package com.example;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    private final UserRepository repo;

    public UserService(UserRepository repo, @Qualifier("smtp") EmailSender sender) {
        this.repo = repo;
    }
}
"""
        file_path = _write_java(tmp_path, src, name="UserService.java")

        from agentic_inquiry.parsers.chain import ParserChain

        chain = ParserChain.from_config()
        parsed = await chain.parse(str(file_path))

        beans = _all_beans(parsed)
        deps = _all_deps(parsed)

        assert any(
            b.source_name == "UserService" and b.metadata["stereotype"] == "Service"
            for b in beans
        ), "UserService should have a spring_di_bean edge after chain parse"

        dep_targets = {d.target_name: d for d in deps}
        assert set(dep_targets) == {"UserRepository", "EmailSender"}, (
            "both constructor param types should appear as deps"
        )
        assert dep_targets["EmailSender"].metadata["qualifier"] == "smtp"
        # Every edge links back to the source file for the graph layer.
        for rel in beans + deps:
            assert rel.target_path == str(file_path)
