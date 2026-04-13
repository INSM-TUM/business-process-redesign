from typing import List, Tuple, Set, Optional
from itertools import chain, combinations, permutations
from adjacency_matrix import AdjacencyMatrix
from dependencies import (
    TemporalDependency,
    ExistentialDependency,
    TemporalType,
    ExistentialType,
    Direction,
)
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

    activities = matrix.get_activities()
    dependencies = matrix.get_dependencies()

    if from_activity not in activities:
        raise ValueError(f"Activity {from_activity} not found in matrix")

    if to_activity not in activities:
        raise ValueError(f"Activity {to_activity} not found in matrix")

    new_matrix = AdjacencyMatrix(activities)

    for (from_act, to_act), (
        temporal_dependency,
        existential_dependency,
    ) in dependencies.items():
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

    from optimized_acceptance_variants import (
        generate_optimized_acceptance_variants as generate_acceptance_variants,
    )
    from variants_to_matrix import variants_to_matrix

    variants = generate_acceptance_variants(new_matrix)
    new_matrix = variants_to_matrix(variants, matrix.activities)

    return new_matrix


def _powerset(iterable):
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(len(s) + 1))


def _convert_direct_to_eventual(matrix: AdjacencyMatrix) -> AdjacencyMatrix:
    """
    Convert all DIRECT temporal dependencies to EVENTUAL.

    Args:
        matrix: The input adjacency matrix

    Returns:
        A new adjacency matrix with all direct temporal dependencies converted to eventual
    """
    activities = matrix.get_activities()
    dependencies = matrix.get_dependencies()

    new_matrix = AdjacencyMatrix(activities)

    for (from_act, to_act), (temporal_dep, existential_dep) in dependencies.items():
        # Convert DIRECT to EVENTUAL
        if temporal_dep.type == TemporalType.DIRECT:
            temporal_dep = TemporalDependency(
                TemporalType.EVENTUAL, direction=temporal_dep.direction
            )

        new_matrix.add_dependency(from_act, to_act, temporal_dep, existential_dep)

    return new_matrix


def _validate_existential_for_subset(
    subset: Tuple[str, ...], dependencies: dict, all_activities: List[str]
) -> bool:
    """
    Check if a subset satisfies all existential dependencies.

    Args:
        subset: A subset of activities (tuple of activity names)
        dependencies: Dictionary of all dependencies
        all_activities: List of all activities in the process

    Returns:
        True if the subset satisfies all existential constraints, False otherwise
    """
    subset_set = set(subset)

    for (from_act, to_act), (temporal_dep, existential_dep) in dependencies.items():
        source_present = from_act in subset_set
        target_present = to_act in subset_set

        if not check_existential_relationship(
            source_present,
            target_present,
            existential_dep.type,
            existential_dep.direction,
        ):
            return False

    return True


def _validate_temporal_for_permutation(
    permutation: Tuple[str, ...], dependencies: dict
) -> bool:
    """
    Check if a permutation satisfies all temporal dependencies.

    Args:
        permutation: An ordered sequence of activities
        dependencies: Dictionary of all dependencies

    Returns:
        True if the permutation satisfies all temporal constraints, False otherwise
    """
    # Create position mapping for quick lookup
    position_map = {activity: idx for idx, activity in enumerate(permutation)}

    for (from_act, to_act), (temporal_dep, existential_dep) in dependencies.items():
        # Only check temporal constraints if both activities are in the permutation
        if from_act in position_map and to_act in position_map:
            source_pos = position_map[from_act]
            target_pos = position_map[to_act]

            if not check_temporal_relationship(
                source_pos, target_pos, temporal_dep.type, temporal_dep.direction
            ):
                return False

    return True


def _compare_matrices(
    original: AdjacencyMatrix, modified: AdjacencyMatrix, modification_set: set
) -> List[Tuple[str, str]]:
    """
    Compare two matrices and return list of changed dependency cells.

    Reports ALL differences between original and modified matrices, including
    cascading secondary changes caused by the modification.

    Args:
        original: The original adjacency matrix
        modified: The modified adjacency matrix
        modification_set: Set of (from, to) tuples that were modified (not currently used)

    Returns:
        List of tuples (from_activity, to_activity) that have changed
    """
    changed_cells = []

    original_deps = original.get_dependencies()
    modified_deps = modified.get_dependencies()

    all_pairs = set(original_deps.keys()) | set(modified_deps.keys())

    for from_act, to_act in sorted(all_pairs):
        original_dep = original_deps.get((from_act, to_act))
        modified_dep = modified_deps.get((from_act, to_act))

        # Check if there's a meaningful difference
        # Note: INDEPENDENCE temporal + any existential is equivalent to (None, existential)
        # when two activities never co-occur in acceptance sequences
        if original_dep != modified_dep:
            # Special case: If one has (INDEPENDENCE, X) and other has (None, X), they're equivalent
            if original_dep and modified_dep:
                orig_temp, orig_exist = original_dep
                mod_temp, mod_exist = modified_dep

                # If temporal differs but one is INDEPENDENCE and one is None, and existential is same
                if orig_exist == mod_exist:
                    if (
                        orig_temp
                        and orig_temp.type == TemporalType.INDEPENDENCE
                        and mod_temp is None
                    ):
                        continue  # Not a real change
                    if (
                        mod_temp
                        and mod_temp.type == TemporalType.INDEPENDENCE
                        and orig_temp is None
                    ):
                        continue  # Not a real change

            changed_cells.append((from_act, to_act))

    return changed_cells


def _format_contradiction_error(
    valid_subsets: List[Tuple[str, ...]],
    valid_permutations: List[Tuple[str, ...]],
    modifications: List[Tuple[str, str, TemporalDependency, ExistentialDependency]],
) -> str:
    """
    Format a detailed error message when contradictions are detected.

    Args:
        valid_subsets: List of valid subsets (empty if existential contradictions)
        valid_permutations: List of valid permutations (empty if temporal contradictions)
        modifications: The modifications that were attempted

    Returns:
        Detailed error message string
    """
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
    Modify multiple dependencies in the adjacency matrix using a variant-based algorithm.

    This function implements a 7-step algorithm:
    1. Create modified matrix (convert direct temporal deps to eventual, apply modifications)
    2. Generate powerset P(A) for all activities
    3. Validate subsets against existential dependencies
    4. Create permutations for valid subsets
    5. Check permutations against temporal dependencies
    6. Rediscover matrix from valid permutations (acceptance sequences)
    7. Compare original and discovered matrices to identify changes

    Args:
        matrix: The input adjacency matrix
        modifications: List of modifications, where each modification is a tuple:
                      (from_activity, to_activity, temporal_dependency, existential_dependency)
                      Note: temporal_direction is ignored (preserved from original or set to FORWARD)

    Returns:
        Tuple of (modified_matrix, changed_cells) where:
        - modified_matrix: The new adjacency matrix with modifications applied
        - changed_cells: List of (from_activity, to_activity) tuples that changed

    Raises:
        ValueError: If any activity in modifications is not found in matrix
        ValueError: If modifications list is empty
        ValueError: If contradictions are detected (with detailed conflict information)
    """
    if not modifications:
        raise ValueError("Modifications list cannot be empty")

    activities = matrix.get_activities()

    for from_act, to_act, _, _ in modifications:
        if from_act not in activities:
            raise ValueError(f"Activity {from_act} not found in matrix")
        if to_act not in activities:
            raise ValueError(f"Activity {to_act} not found in matrix")

    # STEP 1: Create modified matrix
    # Start with original dependencies
    modified_deps = matrix.get_dependencies().copy()

    # (A) Convert all DIRECT temporal dependencies to EVENTUAL
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

    # (B) Apply provided modifications
    for from_act, to_act, temporal_dep, existential_dep in modifications:
        # Check if the pair exists in dependencies
        if (from_act, to_act) in modified_deps:
            # Get existing dependencies
            existing_temporal, existing_existential = modified_deps[(from_act, to_act)]

            # Use the modification's temporal and existential types and directions
            new_temporal = TemporalDependency(
                temporal_dep.type, direction=temporal_dep.direction
            )
            new_existential = ExistentialDependency(
                existential_dep.type, direction=existential_dep.direction
            )

            # Update the forward dependency
            modified_deps[(from_act, to_act)] = (new_temporal, new_existential)

            # Also update reverse dependency if it exists
            if (to_act, from_act) in modified_deps:
                # Create reverse dependencies with inverted directions
                reverse_temporal_dir = (
                    Direction.BOTH
                    if temporal_dep.direction == Direction.BOTH
                    else (
                        Direction.FORWARD
                        if temporal_dep.direction == Direction.BACKWARD
                        else Direction.BACKWARD
                    )
                )
                reverse_existential_dir = (
                    Direction.BOTH
                    if existential_dep.direction == Direction.BOTH
                    else (
                        Direction.FORWARD
                        if existential_dep.direction == Direction.BACKWARD
                        else Direction.BACKWARD
                    )
                )

                reverse_temporal = TemporalDependency(
                    temporal_dep.type, direction=reverse_temporal_dir
                )
                reverse_existential = ExistentialDependency(
                    existential_dep.type, direction=reverse_existential_dir
                )
                modified_deps[(to_act, from_act)] = (
                    reverse_temporal,
                    reverse_existential,
                )
        else:
            # New dependency - use provided directions
            modified_deps[(from_act, to_act)] = (temporal_dep, existential_dep)

    # Rebuild modified matrix with updated dependencies
    modified_matrix = AdjacencyMatrix(activities)
    for (from_act, to_act), (temporal_dep, existential_dep) in modified_deps.items():
        modified_matrix.add_dependency(from_act, to_act, temporal_dep, existential_dep)

    # STEP 2-6: Use optimized acceptance variant generation
    # This handles powersets, existential validation, permutations, and temporal validation
    try:
        from optimized_acceptance_variants import (
            generate_optimized_acceptance_variants as generate_acceptance_variants,
        )

        acceptance_sequences = generate_acceptance_variants(modified_matrix)
    except Exception as e:
        # If variant generation fails, it means there are contradictions
        raise ValueError(
            f"Contradictions detected: modification cannot be implemented.\nAdditional modifications required beyond provided set.\n\nIssue: {str(e)}"
        )

    if not acceptance_sequences:
        raise ValueError(_format_contradiction_error([], [], modifications))

    # STEP 6: Rediscover matrix from acceptance sequences
    from variants_to_matrix import variants_to_matrix

    discovered_matrix = variants_to_matrix(acceptance_sequences, activities)

    # STEP 7: Compare and identify changes
    # Create modification set from the modifications list
    modification_set = {(from_act, to_act) for from_act, to_act, _, _ in modifications}
    changed_cells = _compare_matrices(matrix, discovered_matrix, modification_set)

    return discovered_matrix, changed_cells
