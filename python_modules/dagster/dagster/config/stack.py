from typing import List, NamedTuple, Tuple

from dagster import check


class EvaluationStack(NamedTuple("_EvaluationStack", [("entries", List["EvaluationStackEntry"])])):
    def __new__(cls, entries):
        return super(EvaluationStack, cls).__new__(
            cls,
            check.list_param(entries, "entries", of_type=EvaluationStackEntry),
        )

    @property
    def levels(self) -> List[str]:
        return [
            entry.field_name
            for entry in self.entries
            if isinstance(entry, EvaluationStackPathEntry)
        ]

    def for_field(self, field_name: str) -> "EvaluationStack":
        return EvaluationStack(entries=self.entries + [EvaluationStackPathEntry(field_name)])

    def for_array_index(self, list_index: int) -> "EvaluationStack":
        return EvaluationStack(entries=self.entries + [EvaluationStackListItemEntry(list_index)])


class EvaluationStackEntry:  # marker interface
    pass


class EvaluationStackPathEntry(
    NamedTuple("_EvaluationStackEntry", [("field_name", str)]), EvaluationStackEntry
):
    def __new__(cls, field_name: str):
        return super(EvaluationStackPathEntry, cls).__new__(
            cls,
            check.str_param(field_name, "field_name"),
        )


class EvaluationStackListItemEntry(
    NamedTuple("_EvaluationStackListItemEntry", [("list_index", int)]), EvaluationStackEntry
):
    def __new__(cls, list_index: int):
        check.int_param(list_index, "list_index")
        check.param_invariant(list_index >= 0, "list_index")
        return super(EvaluationStackListItemEntry, cls).__new__(cls, list_index)


def get_friendly_path_msg(stack: EvaluationStack) -> str:
    return get_friendly_path_info(stack)[0]


def get_friendly_path_info(stack: EvaluationStack) -> Tuple[str, str]:
    if not stack.entries:
        path = ""
        path_msg = "at the root"
    else:
        comps = ["root"]
        for entry in stack.entries:
            if isinstance(entry, EvaluationStackPathEntry):
                comp = ":" + entry.field_name
                comps.append(comp)
            elif isinstance(entry, EvaluationStackListItemEntry):
                comps.append("[{i}]".format(i=entry.list_index))
            else:
                check.failed("unsupported")

        path = "".join(comps)
        path_msg = "at path " + path
    return path_msg, path
