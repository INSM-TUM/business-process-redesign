from typing import Tuple, Optional, Dict, List
from dependencies import (
    TemporalDependency,
    ExistentialDependency,
    Direction,
)
from adjacency_matrix import AdjacencyMatrix
from optimized_acceptance_variants import generate_optimized_acceptance_variants as generate_acceptance_variants
from variants_to_matrix import variants_to_matrix
from change_operations.delete_operation import delete_activity_from_variants
from change_operations.insert_operation import insert_into_variants

def move_activity(
        matrix: AdjacencyMatrix,
        activity: str,
        dependencies: Dict[
            Tuple[str, str],
            Tuple[Optional[TemporalDependency], Optional[ExistentialDependency]],
        ],
    ) -> AdjacencyMatrix:
    """
    Moves an activity by updating only the specified dependencies and their reverses.
    This approach directly modifies the matrix to reflect only the requested changes.
    
    Args:
        matrix: The input adjacency matrix
        activity: The name of the activity which should be moved
        dependencies: The dependencies defining the new position of the activity to be moved

    Returns:
        A new adjacency matrix with only the specified dependencies changed
    """
    # Start with a copy of the original matrix
    result_matrix = AdjacencyMatrix(matrix.activities.copy())
    
    # Copy all original dependencies
    for (source, target), (temp_dep, exist_dep) in matrix.get_dependencies().items():
        result_matrix.add_dependency(source, target, temp_dep, exist_dep)
    
    # Update only the specified dependencies and their reverse dependencies
    for (source, target), (temp_dep, exist_dep) in dependencies.items():
        if temp_dep is not None or exist_dep is not None:
            if source in result_matrix.activities and target in result_matrix.activities:
                # Apply the explicitly specified dependency
                result_matrix.add_dependency(source, target, temp_dep, exist_dep)

                # Apply the reverse dependency based on the specified dependency
                if target in result_matrix.activities and source in result_matrix.activities:
                    # Create the reverse temporal dependency
                    reverse_temp = None
                    if temp_dep is not None:
                        if temp_dep.direction == Direction.FORWARD:
                            reverse_temp = TemporalDependency(temp_dep.type, Direction.BACKWARD)
                        elif temp_dep.direction == Direction.BACKWARD:
                            reverse_temp = TemporalDependency(temp_dep.type, Direction.FORWARD)
                        else:  # Direction.BOTH
                            reverse_temp = TemporalDependency(temp_dep.type, Direction.BOTH)

                    # Create the reverse existential dependency
                    reverse_exist = None
                    if exist_dep is not None:
                        if exist_dep.direction == Direction.FORWARD:
                            reverse_exist = ExistentialDependency(exist_dep.type, Direction.BACKWARD)
                        elif exist_dep.direction == Direction.BACKWARD:
                            reverse_exist = ExistentialDependency(exist_dep.type, Direction.BACKWARD)
                        else:  # Direction.BOTH
                            reverse_exist = ExistentialDependency(exist_dep.type, Direction.BOTH)

                    result_matrix.add_dependency(target, source, reverse_temp, reverse_exist)

    return result_matrix

def move_activity_in_variants(
        activity: str,
        dependencies: Dict[
            Tuple[str, str],
            Tuple[Optional[TemporalDependency], Optional[ExistentialDependency]],
        ],
        variants: List[List[str]],
    ) -> List[List[str]]:
    """
    Removes activity from original position and moves it to new position.

    Args:
        activity: The name of the activity which should be moved
        dependencies: The dependencies defining the new position of the activity to be moved
        variants: The variants of the original matrix

    Returns:
        A new adjacency matrix with the activity moved

    Raises:
        ValueError: If input produces contradiction
    """
    variants_after_delete = delete_activity_from_variants(variants, activity)
    matrix_after_delete = variants_to_matrix(variants_after_delete)

    total_dependencies = matrix_after_delete.get_dependencies() | dependencies
    try:
        new_variants = insert_into_variants(activity, dependencies, total_dependencies , matrix_after_delete.activities, variants_after_delete)
    except ValueError as e:
        raise ValueError(f"The input is invalid: {e}")

    return new_variants