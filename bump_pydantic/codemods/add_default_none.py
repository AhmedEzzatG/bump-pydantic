from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.metadata import FullyQualifiedNameProvider, QualifiedName

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor


class AddDefaultNoneCommand(VisitorBasedCodemodCommand):
    """This codemod adds the default value `None` to all fields of a pydantic model that
    are either type `Optional[T]`, `Union[T, None]` or `Any`.

    Example::
        # Before
        ```py
        from pydantic import BaseModel

        class Foo(BaseModel):
            bar: Optional[str]
            baz: Union[str, None]
            qux: Any
        ```

        # After
        ```py
        from pydantic import BaseModel

        class Foo(BaseModel):
            bar: Optional[str] = None
            baz: Union[str, None] = None
            qux: Any = None
        ```
    """

    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider,)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.inside_base_model = False
        self.should_add_none = False

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        fqn_set = self.get_metadata(FullyQualifiedNameProvider, node)

        if not fqn_set:
            return None

        fqn: QualifiedName = next(iter(fqn_set))  # type: ignore
        if fqn.name in self.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY]:
            self.inside_base_model = True

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        self.inside_base_model = False
        return updated_node

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if m.matches(
            node.annotation.annotation,
            m.Subscript(m.Name("Optional") | m.Attribute(m.Name("typing"), m.Name("Optional")))
            | m.Subscript(
                m.Name("Union") | m.Attribute(m.Name("typing"), m.Name("Union")),
                slice=[
                    m.ZeroOrMore(),
                    m.SubscriptElement(slice=m.Index(m.Name("None"))),
                    m.ZeroOrMore(),
                ],
            )
            | m.Name("Any")
            | m.Attribute(m.Name("typing"), m.Name("Any"))
            # TODO: This can be recursive. Can it?
            | m.BinaryOperation(operator=m.BitOr(), left=m.Name("None"))
            | m.BinaryOperation(operator=m.BitOr(), right=m.Name("None")),
        ):
            self.should_add_none = True
        return None

    def _handle_leave_AnnAssign_add_deafult_none(self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign) -> cst.AnnAssign:
        if not self.inside_base_model:
            return updated_node

        if not self.should_add_none:
            return updated_node

        if updated_node.value is None:
            updated_node = updated_node.with_changes(value=cst.Name("None"))

        elif m.matches(updated_node.value, m.Call(func=m.Name("Field"))):
            assert isinstance(updated_node.value, cst.Call)
            args = updated_node.value.args
            if args:
                # NOTE: It has a "default" value as positional argument. Nothing to do.
                if args[0].keyword is None:
                    ...
                # NOTE: It has a "default" or "default_factory" keyword argument. Nothing to do.
                elif any(arg.keyword and arg.keyword.value in ("default", "default_factory") for arg in args):
                    ...
                else:
                    updated_node = updated_node.with_changes(
                        value=updated_node.value.with_changes(args=[cst.Arg(value=cst.Name("None")), *args])
                    )

            # NOTE: This is the case where `Field` is called without any arguments e.g. `Field()`.
            else:
                updated_node = updated_node.with_changes(
                    value=updated_node.value.with_changes(args=[cst.Arg(value=cst.Name("None"))])  # type: ignore
                )
        return updated_node

    # add optional if the assignment has a default value
    def _handle_leave_AnnAssign_add_optional_for_default(self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign) -> cst.AnnAssign:
        if not self.inside_base_model or self.should_add_none:
            return updated_node

        if updated_node.value is None:
            return updated_node

        new_annotation = cst.Subscript(
            value=cst.Name("Optional"),
            slice=[cst.SubscriptElement(cst.Index(updated_node.annotation.annotation))]
        )

        if m.matches(updated_node.value, m.Call(func=m.Name("Field"))):
            args = updated_node.value.args

            if args:
                # NOTE: It has a "default" value as positional argument. Nothing to do.
                if args[0].keyword is None:
                    updated_node = updated_node.with_changes(
                        annotation=updated_node.annotation.with_changes(annotation=new_annotation))
                # NOTE: It has a "default" or "default_factory" keyword argument. Nothing to do.
                elif any(arg.keyword and arg.keyword.value in ("default", "default_factory") for arg in args):
                    updated_node = updated_node.with_changes(
                        annotation=updated_node.annotation.with_changes(annotation=new_annotation))

            return updated_node

        updated_node = updated_node.with_changes(
            annotation=updated_node.annotation.with_changes(annotation=new_annotation))

        return updated_node


    def leave_AnnAssign(self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign) -> cst.AnnAssign:
        if self.inside_base_model and self.should_add_none:
            if updated_node.value is None:
                updated_node = updated_node.with_changes(value=cst.Name("None"))
            elif m.matches(updated_node.value, m.Call(func=m.Name("Field"))):
                assert isinstance(updated_node.value, cst.Call)
                args = updated_node.value.args
                if args:
                    # NOTE: It has a "default" value as positional argument. Nothing to do.
                    if args[0].keyword is None:
                        ...
                    # NOTE: It has a "default" or "default_factory" keyword argument. Nothing to do.
                    elif any(arg.keyword and arg.keyword.value in ("default", "default_factory") for arg in args):
                        ...
                    else:
                        updated_node = updated_node.with_changes(
                            value=updated_node.value.with_changes(args=[cst.Arg(value=cst.Name("None")), *args])
                        )

                # NOTE: This is the case where `Field` is called without any arguments e.g. `Field()`.
                else:
                    updated_node = updated_node.with_changes(
                        value=updated_node.value.with_changes(args=[cst.Arg(value=cst.Name("None"))])  # type: ignore
                    )

        updated_node = self._handle_leave_AnnAssign_add_optional_for_default(original_node, updated_node)

        self.inside_an_assign = False
        self.should_add_none = False
        return updated_node


if __name__ == "__main__":
    import os
    import textwrap
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from libcst.metadata import FullRepoManager

    with TemporaryDirectory(dir=os.getcwd()) as tmpdir:
        package_dir = f"{tmpdir}/package"
        os.mkdir(package_dir)
        module_path = f"{package_dir}/a.py"
        with open(module_path, "w") as f:
            content = textwrap.dedent(
                """
                from pydantic import BaseModel

                class Foo(BaseModel):
                    a: Optional[str]

                class Bar(Foo):
                    b: Optional[str]
                    c: Union[str, None]
                    d: Any

                foo = Foo(a="text")
                foo.dict()
            """
            )
            f.write(content)
        module = str(Path(module_path).relative_to(tmpdir))
        mrg = FullRepoManager(tmpdir, {module}, providers={FullyQualifiedNameProvider})
        wrapper = mrg.get_metadata_wrapper_for_path(module)
        context = CodemodContext(wrapper=wrapper)

        command = AddDefaultNoneCommand(context=context)  # type: ignore[assignment]
        mod = wrapper.visit(command)
        print(mod.code)
