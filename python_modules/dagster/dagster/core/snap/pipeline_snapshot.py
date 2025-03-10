from typing import AbstractSet, Any, Dict, List, NamedTuple, Optional, Union, cast

from dagster import Field, Permissive, Selector, Shape, check
from dagster.config.config_type import (
    Array,
    ConfigTypeKind,
    Enum,
    EnumValue,
    Noneable,
    ScalarUnion,
    get_builtin_scalar_by_name,
)
from dagster.config.field_utils import FIELD_NO_DEFAULT_PROVIDED
from dagster.config.snap import (
    ConfigEnumValueSnap,
    ConfigFieldSnap,
    ConfigSchemaSnapshot,
    ConfigType,
    ConfigTypeSnap,
)
from dagster.core.definitions.job_definition import JobDefinition
from dagster.core.definitions.pipeline_definition import (
    PipelineDefinition,
    PipelineSubsetDefinition,
)
from dagster.core.utils import toposort_flatten
from dagster.serdes import (
    DefaultNamedTupleSerializer,
    create_snapshot_id,
    deserialize_value,
    unpack_inner_value,
    whitelist_for_serdes,
)

from .config_types import build_config_schema_snapshot
from .dagster_types import DagsterTypeNamespaceSnapshot, build_dagster_type_namespace_snapshot
from .dep_snapshot import (
    DependencyStructureSnapshot,
    build_dep_structure_snapshot_from_icontains_solids,
)
from .mode import ModeDefSnap, build_mode_def_snap
from .solid import (
    CompositeSolidDefSnap,
    SolidDefSnap,
    SolidDefinitionsSnapshot,
    build_solid_definitions_snapshot,
)


def create_pipeline_snapshot_id(snapshot: "PipelineSnapshot") -> str:
    check.inst_param(snapshot, "snapshot", PipelineSnapshot)
    return create_snapshot_id(snapshot)


class PipelineSnapshotSerializer(DefaultNamedTupleSerializer):
    @classmethod
    def value_from_storage_dict(
        cls,
        storage_dict,
        klass,
        args_for_class,
        whitelist_map,
        descent_path,
    ):
        # unpack all stored fields
        unpacked_dict = {
            key: unpack_inner_value(value, whitelist_map, f"{descent_path}.{key}")
            for key, value in storage_dict.items()
        }
        # called by the serdes layer, delegates to helper method with expanded kwargs
        return _pipeline_snapshot_from_storage(**unpacked_dict)


def _pipeline_snapshot_from_storage(
    name: str,
    description: Optional[str],
    tags: Optional[Dict[str, Any]],
    config_schema_snapshot: ConfigSchemaSnapshot,
    dagster_type_namespace_snapshot: DagsterTypeNamespaceSnapshot,
    solid_definitions_snapshot: SolidDefinitionsSnapshot,
    dep_structure_snapshot: DependencyStructureSnapshot,
    mode_def_snaps: List[ModeDefSnap],
    lineage_snapshot: Optional["PipelineSnapshotLineage"] = None,
    graph_def_name: Optional[str] = None,
) -> "PipelineSnapshot":
    """
    v0
    v1:
        - lineage added
    v2:
        - graph_def_name
    """
    if graph_def_name is None:
        graph_def_name = name

    return PipelineSnapshot(
        name=name,
        description=description,
        tags=tags,
        config_schema_snapshot=config_schema_snapshot,
        dagster_type_namespace_snapshot=dagster_type_namespace_snapshot,
        solid_definitions_snapshot=solid_definitions_snapshot,
        dep_structure_snapshot=dep_structure_snapshot,
        mode_def_snaps=mode_def_snaps,
        lineage_snapshot=lineage_snapshot,
        graph_def_name=graph_def_name,
    )


@whitelist_for_serdes(serializer=PipelineSnapshotSerializer)
class PipelineSnapshot(
    NamedTuple(
        "_PipelineSnapshot",
        [
            ("name", str),
            ("description", Optional[str]),
            ("tags", Dict[str, Any]),
            ("config_schema_snapshot", ConfigSchemaSnapshot),
            ("dagster_type_namespace_snapshot", DagsterTypeNamespaceSnapshot),
            ("solid_definitions_snapshot", SolidDefinitionsSnapshot),
            ("dep_structure_snapshot", DependencyStructureSnapshot),
            ("mode_def_snaps", List[ModeDefSnap]),
            ("lineage_snapshot", Optional["PipelineSnapshotLineage"]),
            ("graph_def_name", str),
        ],
    )
):
    def __new__(
        cls,
        name: str,
        description: Optional[str],
        tags: Optional[Dict[str, Any]],
        config_schema_snapshot: ConfigSchemaSnapshot,
        dagster_type_namespace_snapshot: DagsterTypeNamespaceSnapshot,
        solid_definitions_snapshot: SolidDefinitionsSnapshot,
        dep_structure_snapshot: DependencyStructureSnapshot,
        mode_def_snaps: List[ModeDefSnap],
        lineage_snapshot: Optional["PipelineSnapshotLineage"],
        graph_def_name: str,
    ):
        return super(PipelineSnapshot, cls).__new__(
            cls,
            name=check.str_param(name, "name"),
            description=check.opt_str_param(description, "description"),
            tags=check.opt_dict_param(tags, "tags"),
            config_schema_snapshot=check.inst_param(
                config_schema_snapshot, "config_schema_snapshot", ConfigSchemaSnapshot
            ),
            dagster_type_namespace_snapshot=check.inst_param(
                dagster_type_namespace_snapshot,
                "dagster_type_namespace_snapshot",
                DagsterTypeNamespaceSnapshot,
            ),
            solid_definitions_snapshot=check.inst_param(
                solid_definitions_snapshot, "solid_definitions_snapshot", SolidDefinitionsSnapshot
            ),
            dep_structure_snapshot=check.inst_param(
                dep_structure_snapshot, "dep_structure_snapshot", DependencyStructureSnapshot
            ),
            mode_def_snaps=check.list_param(mode_def_snaps, "mode_def_snaps", of_type=ModeDefSnap),
            lineage_snapshot=check.opt_inst_param(
                lineage_snapshot, "lineage_snapshot", PipelineSnapshotLineage
            ),
            graph_def_name=check.str_param(graph_def_name, "graph_def_name"),
        )

    @classmethod
    def from_pipeline_def(cls, pipeline_def: PipelineDefinition) -> "PipelineSnapshot":
        check.inst_param(pipeline_def, "pipeline_def", PipelineDefinition)
        lineage = None
        if isinstance(pipeline_def, PipelineSubsetDefinition):

            lineage = PipelineSnapshotLineage(
                parent_snapshot_id=create_pipeline_snapshot_id(
                    cls.from_pipeline_def(pipeline_def.parent_pipeline_def)
                ),
                solid_selection=sorted(pipeline_def.solid_selection),
                solids_to_execute=pipeline_def.solids_to_execute,
            )
        if isinstance(pipeline_def, JobDefinition) and pipeline_def.op_selection_data:

            lineage = PipelineSnapshotLineage(
                parent_snapshot_id=create_pipeline_snapshot_id(
                    cls.from_pipeline_def(pipeline_def.op_selection_data.parent_job_def)
                ),
                solid_selection=sorted(pipeline_def.op_selection_data.op_selection),
                solids_to_execute=pipeline_def.op_selection_data.resolved_op_selection,
            )

        return PipelineSnapshot(
            name=pipeline_def.name,
            description=pipeline_def.description,
            tags=pipeline_def.tags,
            config_schema_snapshot=build_config_schema_snapshot(pipeline_def),
            dagster_type_namespace_snapshot=build_dagster_type_namespace_snapshot(pipeline_def),
            solid_definitions_snapshot=build_solid_definitions_snapshot(pipeline_def),
            dep_structure_snapshot=build_dep_structure_snapshot_from_icontains_solids(
                pipeline_def.graph
            ),
            mode_def_snaps=[
                build_mode_def_snap(md, pipeline_def.get_run_config_schema(md.name).config_type.key)
                for md in pipeline_def.mode_definitions
            ],
            lineage_snapshot=lineage,
            graph_def_name=pipeline_def.graph.name,
        )

    def get_node_def_snap(self, solid_def_name: str) -> Union[SolidDefSnap, CompositeSolidDefSnap]:
        check.str_param(solid_def_name, "solid_def_name")
        for solid_def_snap in self.solid_definitions_snapshot.solid_def_snaps:
            if solid_def_snap.name == solid_def_name:
                return solid_def_snap

        for comp_solid_def_snap in self.solid_definitions_snapshot.composite_solid_def_snaps:
            if comp_solid_def_snap.name == solid_def_name:
                return comp_solid_def_snap

        check.failed("not found")

    def has_solid_name(self, solid_name: str) -> bool:
        check.str_param(solid_name, "solid_name")
        for solid_snap in self.dep_structure_snapshot.solid_invocation_snaps:
            if solid_snap.solid_name == solid_name:
                return True
        return False

    def get_config_type_from_solid_def_snap(
        self,
        solid_def_snap: Union[SolidDefSnap, CompositeSolidDefSnap],
    ) -> Optional[ConfigType]:
        check.inst_param(solid_def_snap, "solid_def_snap", (SolidDefSnap, CompositeSolidDefSnap))
        if solid_def_snap.config_field_snap:
            config_type_key = solid_def_snap.config_field_snap.type_key
            if self.config_schema_snapshot.has_config_snap(config_type_key):
                return construct_config_type_from_snap(
                    self.config_schema_snapshot.get_config_snap(config_type_key),
                    self.config_schema_snapshot.all_config_snaps_by_key,
                )
        return None

    @property
    def solid_names(self) -> List[str]:
        return [ss.solid_name for ss in self.dep_structure_snapshot.solid_invocation_snaps]

    @property
    def solid_names_in_topological_order(self) -> List[str]:
        upstream_outputs = {}

        for solid_invocation_snap in self.dep_structure_snapshot.solid_invocation_snaps:
            solid_name = solid_invocation_snap.solid_name
            upstream_outputs[solid_name] = {
                upstream_output_snap.solid_name
                for input_dep_snap in solid_invocation_snap.input_dep_snaps
                for upstream_output_snap in input_dep_snap.upstream_output_snaps
            }

        return toposort_flatten(upstream_outputs)


def _construct_enum_from_snap(config_type_snap: ConfigTypeSnap):
    enum_values = check.list_param(config_type_snap.enum_values, "enum_values", ConfigEnumValueSnap)

    return Enum(
        name=config_type_snap.key,
        enum_values=[
            EnumValue(enum_value_snap.value, description=enum_value_snap.description)
            for enum_value_snap in enum_values
        ],
    )


def _construct_fields(
    config_type_snap: ConfigTypeSnap,
    config_snap_map: Dict[str, ConfigTypeSnap],
) -> Dict[str, Field]:
    fields = check.not_none(config_type_snap.fields)
    return {
        cast(str, field.name): Field(
            construct_config_type_from_snap(config_snap_map[field.type_key], config_snap_map),
            description=field.description,
            is_required=field.is_required,
            default_value=deserialize_value(cast(str, field.default_value_as_json_str))
            if field.default_provided
            else FIELD_NO_DEFAULT_PROVIDED,
        )
        for field in fields
    }


def _construct_selector_from_snap(config_type_snap, config_snap_map):
    check.list_param(config_type_snap.fields, "config_field_snap", ConfigFieldSnap)

    return Selector(
        fields=_construct_fields(config_type_snap, config_snap_map),
        description=config_type_snap.description,
    )


def _construct_shape_from_snap(config_type_snap, config_snap_map):
    check.list_param(config_type_snap.fields, "config_field_snap", ConfigFieldSnap)

    return Shape(
        fields=_construct_fields(config_type_snap, config_snap_map),
        description=config_type_snap.description,
    )


def _construct_permissive_from_snap(config_type_snap, config_snap_map):
    check.opt_list_param(config_type_snap.fields, "config_field_snap", ConfigFieldSnap)

    return Permissive(
        fields=_construct_fields(config_type_snap, config_snap_map),
        description=config_type_snap.description,
    )


def _construct_scalar_union_from_snap(config_type_snap, config_snap_map):
    check.list_param(config_type_snap.type_param_keys, "type_param_keys", str)
    check.invariant(
        len(config_type_snap.type_param_keys) == 2,
        "Expect SCALAR_UNION to provide a scalar key and a non scalar key. Snapshot Provided: {}".format(
            config_type_snap.type_param_keys
        ),
    )

    return ScalarUnion(
        scalar_type=construct_config_type_from_snap(
            config_snap_map[config_type_snap.type_param_keys[0]], config_snap_map
        ),
        non_scalar_schema=construct_config_type_from_snap(
            config_snap_map[config_type_snap.type_param_keys[1]], config_snap_map
        ),
    )


def _construct_array_from_snap(config_type_snap, config_snap_map):
    check.list_param(config_type_snap.type_param_keys, "type_param_keys", str)
    check.invariant(
        len(config_type_snap.type_param_keys) == 1,
        "Expect ARRAY to provide a single inner type. Snapshot provided: {}".format(
            config_type_snap.type_param_keys
        ),
    )

    return Array(
        inner_type=construct_config_type_from_snap(
            config_snap_map[config_type_snap.type_param_keys[0]], config_snap_map
        )
    )


def _construct_noneable_from_snap(config_type_snap, config_snap_map):
    check.list_param(config_type_snap.type_param_keys, "type_param_keys", str)
    check.invariant(
        len(config_type_snap.type_param_keys) == 1,
        "Expect NONEABLE to provide a single inner type. Snapshot provided: {}".format(
            config_type_snap.type_param_keys
        ),
    )
    return Noneable(
        construct_config_type_from_snap(
            config_snap_map[config_type_snap.type_param_keys[0]], config_snap_map
        )
    )


def construct_config_type_from_snap(
    config_type_snap: ConfigTypeSnap, config_snap_map: Dict[str, ConfigTypeSnap]
) -> ConfigType:
    check.inst_param(config_type_snap, "config_type_snap", ConfigTypeSnap)
    check.dict_param(config_snap_map, "config_snap_map", key_type=str, value_type=ConfigTypeSnap)

    if config_type_snap.kind in (ConfigTypeKind.SCALAR, ConfigTypeKind.ANY):
        return get_builtin_scalar_by_name(config_type_snap.key)
    elif config_type_snap.kind == ConfigTypeKind.ENUM:
        return _construct_enum_from_snap(config_type_snap)
    elif config_type_snap.kind == ConfigTypeKind.SELECTOR:
        return _construct_selector_from_snap(config_type_snap, config_snap_map)
    elif config_type_snap.kind == ConfigTypeKind.STRICT_SHAPE:
        return _construct_shape_from_snap(config_type_snap, config_snap_map)
    elif config_type_snap.kind == ConfigTypeKind.PERMISSIVE_SHAPE:
        return _construct_permissive_from_snap(config_type_snap, config_snap_map)
    elif config_type_snap.kind == ConfigTypeKind.SCALAR_UNION:
        return _construct_scalar_union_from_snap(config_type_snap, config_snap_map)
    elif config_type_snap.kind == ConfigTypeKind.ARRAY:
        return _construct_array_from_snap(config_type_snap, config_snap_map)
    elif config_type_snap.kind == ConfigTypeKind.NONEABLE:
        return _construct_noneable_from_snap(config_type_snap, config_snap_map)
    check.failed("Could not evaluate config type snap kind: {}".format(config_type_snap.kind))


@whitelist_for_serdes
class PipelineSnapshotLineage(
    NamedTuple(
        "_PipelineSnapshotLineage",
        [
            ("parent_snapshot_id", str),
            ("solid_selection", Optional[List[str]]),
            ("solids_to_execute", Optional[AbstractSet[str]]),
        ],
    )
):
    def __new__(
        cls,
        parent_snapshot_id: str,
        solid_selection: Optional[List[str]] = None,
        solids_to_execute: Optional[AbstractSet[str]] = None,
    ):
        check.opt_set_param(solids_to_execute, "solids_to_execute", of_type=str)
        return super(PipelineSnapshotLineage, cls).__new__(
            cls,
            check.str_param(parent_snapshot_id, parent_snapshot_id),
            solid_selection,
            solids_to_execute,
        )
