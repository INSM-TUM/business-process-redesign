from typing import Optional, List, Tuple
from itertools import chain, combinations
from adjacency_matrix import AdjacencyMatrix
from optimized_acceptance_variants import (
    generate_optimized_acceptance_variants as generate_acceptance_variants,
)
from dependencies import (
    TemporalDependency,
    ExistentialDependency,
    TemporalType,
    ExistentialType,
    Direction,
)
from variants_to_matrix import variants_to_matrix
from constraint_logic import check_temporal_relationship, check_existential_relationship


def modify_dependency(
    matrix: AdjacencyMatrix,
    from_activity: str,
    to_activity: str,
    temporal_dep: Optional[TemporalType],
    existential_dep: Optional[ExistentialType],
    temporal_direction: Optional[Direction] = None,
    existential_direction: Optional[Direction] = None,
) -> AdjacencyMatrix:
    """
    Modify a dependency with activities which are part of the process:
    1. Check that activities from_activity and to_activity are part of activities
    2. Search for dependency and change the old dependency to the new activity

    Args:
        matrix: The input adjacency matrix
        from_activity: The name of the activity from which the depenency is seen
        to_activity: The name of the activity to which the dependency is seen
        exist_dependency: Existential dependency which should become the new one

    Returns:
        A new adjacency matrix with the adapted dependency

    Raises:
        ValueError: If from_activity not found
        ValueError: If to_activity not found in matrix
    """

    # modify the name of the activity to be replaced by the newly named activity
    activities = matrix.get_activities()
    dependencies = matrix.get_dependencies()

    # check that activities are actually part of the matrix
    if from_activity not in activities:
        raise ValueError(f"Activity {from_activity} not found in matrix")

    if to_activity not in activities:
        raise ValueError(f"Activity {to_activity} not found in matrix")

    # here we must consider the order in which the implication currently is cause the change operation needs to be adapted accordingly
    # replace in dict with dependencies
    new_matrix = AdjacencyMatrix(activities)

    # iterate over all dependencies which are part of the process
    for (from_act, to_act), (
        temporal_dependency,
        existential_dependency,
    ) in dependencies.items():
        # way as also written in method call - no inversion of the dependency needed
        if from_act == from_activity and to_act == to_activity:
            if existential_dep:
                direction = (
                    existential_direction
                    if existential_direction is not None
                    else existential_dependency.direction
                )
                existential_dependency = ExistentialDependency(
                    existential_dep, direction=direction
                )
            if temporal_dep:
                direction = (
                    temporal_direction
                    if temporal_direction is not None
                    else temporal_dependency.direction
                )
                temporal_dependency = TemporalDependency(
                    temporal_dep, direction=direction
                )
        elif from_act == to_activity and to_act == from_activity:
            if existential_dep:
                if (
                    existential_direction is not None
                    and existential_direction != Direction.BOTH
                ):
                    existential_direction = (
                        Direction.FORWARD
                        if existential_direction == Direction.BACKWARD
                        else Direction.BACKWARD
                    )
                direction = (
                    existential_direction
                    if existential_direction is not None
                    else existential_dependency.direction
                )
                existential_dependency = ExistentialDependency(
                    existential_dep, direction=direction
                )
            if temporal_dep:
                if (
                    temporal_direction is not None
                    and temporal_direction != Direction.BOTH
                ):
                    temporal_direction = (
                        Direction.FORWARD
                        if temporal_direction == Direction.BACKWARD
                        else Direction.BACKWARD
                    )
                direction = (
                    temporal_direction
                    if temporal_direction is not None
                    else temporal_dependency.direction
                )
                temporal_dependency = TemporalDependency(
                    temporal_dep, direction=direction
                )

        new_matrix.add_dependency(
            from_act, to_act, temporal_dependency, existential_dependency
        )

    variants = generate_acceptance_variants(new_matrix)
    if not variants:
        raise ValueError(
            "Modification creates a contradiction — no valid process variants exist."
        )

    return new_matrix


# ---------------------------------------------------------------------------
# Helpers for modify_dependencies
# ---------------------------------------------------------------------------


def _compare_matrices(
    original: AdjacencyMatrix, modified: AdjacencyMatrix, modification_set: set
) -> List[Tuple[str, str]]:
    changed_cells = []
    original_deps = original.get_dependencies()
    modified_deps = modified.get_dependencies()
    all_pairs = set(original_deps.keys()) | set(modified_deps.keys())
    for from_act, to_act in sorted(all_pairs):
        original_dep = original_deps.get((from_act, to_act))
        modified_dep = modified_deps.get((from_act, to_act))
        if original_dep != modified_dep:
            if original_dep and modified_dep:
                orig_temp, orig_exist = original_dep
                mod_temp, mod_exist = modified_dep
                if orig_exist == mod_exist:
                    if (
                        orig_temp
                        and orig_temp.type == TemporalType.INDEPENDENCE
                        and mod_temp is None
                    ):
                        continue
                    if (
                        mod_temp
                        and mod_temp.type == TemporalType.INDEPENDENCE
                        and orig_temp is None
                    ):
                        continue
            changed_cells.append((from_act, to_act))
    return changed_cells


def _format_contradiction_error(
    valid_subsets,
    valid_permutations,
    modifications,
) -> str:
    error_msg = "Contradictions detected: modification cannot be implemented.\n"
    error_msg += "Additional modifications required beyond provided set.\n\n"
    if not valid_subsets:
        error_msg += "Issue: Existential dependency contradictions detected.\n"
        error_msg += "The provided modifications create existential constraints that cannot be satisfied.\n"
        error_msg += (
            f"Attempted modifications: {len(modifications)} dependency/dependencies\n"
        )
    elif not valid_permutations:
        error_msg += "Issue: Temporal dependency contradictions detected.\n"
        error_msg += "The provided modifications create temporal constraints that cannot be satisfied.\n"
        error_msg += f"Valid activity subsets found: {len(valid_subsets)}\n"
        error_msg += "However, no valid execution orderings exist for these subsets.\n"
    return error_msg


def modify_dependencies(
    matrix: AdjacencyMatrix,
    modifications: List[Tuple[str, str, TemporalDependency, ExistentialDependency]],
) -> Tuple[AdjacencyMatrix, List[Tuple[str, str]]]:
    """
    Modify multiple dependencies using a variant-based 7-step algorithm.

    Raises:
        ValueError: If any activity not found, list empty, or contradictions detected.
    """
    if not modifications:
        raise ValueError("Modifications list cannot be empty")

    activities = matrix.get_activities()
    for from_act, to_act, _, _ in modifications:
        if from_act not in activities:
            raise ValueError(f"Activity {from_act} not found in matrix")
        if to_act not in activities:
            raise ValueError(f"Activity {to_act} not found in matrix")

    # STEP 1: Build modified deps dict
    modified_deps = matrix.get_dependencies().copy()

    # (A) Convert DIRECT → EVENTUAL
    for (from_act, to_act), (temporal_dep, existential_dep) in list(
        modified_deps.items()
    ):
        if temporal_dep.type == TemporalType.DIRECT:
            modified_deps[(from_act, to_act)] = (
                TemporalDependency(
                    TemporalType.EVENTUAL, direction=temporal_dep.direction
                ),
                existential_dep,
            )

    # (B) Apply modifications
    for from_act, to_act, temporal_dep, existential_dep in modifications:
        if (from_act, to_act) in modified_deps:
            new_temporal = TemporalDependency(
                temporal_dep.type, direction=temporal_dep.direction
            )
            new_existential = ExistentialDependency(
                existential_dep.type, direction=existential_dep.direction
            )
            modified_deps[(from_act, to_act)] = (new_temporal, new_existential)
            if (to_act, from_act) in modified_deps:
                rev_t_dir = (
                    Direction.BOTH
                    if temporal_dep.direction == Direction.BOTH
                    else (
                        Direction.FORWARD
                        if temporal_dep.direction == Direction.BACKWARD
                        else Direction.BACKWARD
                    )
                )
                rev_e_dir = (
                    Direction.BOTH
                    if existential_dep.direction == Direction.BOTH
                    else (
                        Direction.FORWARD
                        if existential_dep.direction == Direction.BACKWARD
                        else Direction.BACKWARD
                    )
                )
                modified_deps[(to_act, from_act)] = (
                    TemporalDependency(temporal_dep.type, direction=rev_t_dir),
                    ExistentialDependency(existential_dep.type, direction=rev_e_dir),
                )
        else:
            modified_deps[(from_act, to_act)] = (temporal_dep, existential_dep)

    modified_matrix = AdjacencyMatrix(activities)
    for (from_act, to_act), (t, e) in modified_deps.items():
        modified_matrix.add_dependency(from_act, to_act, t, e)

    # STEPS 2-6: Generate acceptance variants
    try:
        acceptance_sequences = generate_acceptance_variants(modified_matrix)
    except Exception as e:
        raise ValueError(
            f"Contradictions detected: modification cannot be implemented.\n"
            f"Additional modifications required beyond provided set.\n\nIssue: {str(e)}"
        )

    if not acceptance_sequences:
        raise ValueError(_format_contradiction_error([], [], modifications))

    # STEP 6: Rediscover matrix
    discovered_matrix = variants_to_matrix(acceptance_sequences, activities)

    # STEP 7: Compare
    modification_set = {(f, t) for f, t, _, _ in modifications}
    changed_cells = _compare_matrices(matrix, discovered_matrix, modification_set)

    return discovered_matrix, changed_cells
