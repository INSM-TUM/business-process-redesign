import sys
import os
import yaml
import copy
from werkzeug.utils import secure_filename
from adjacency_matrix import parse_yaml_to_adjacency_matrix


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify
import json
from variants_to_matrix import variants_to_matrix
from dependencies import TemporalType, ExistentialType, Direction, TemporalDependency, ExistentialDependency
from change_operations.delete_operation import delete_activity
from change_operations.insert_operation import insert_activity
from change_operations.swap_operation import swap_activities
from change_operations.skip_operation import skip_activity
from change_operations.replace_operation import replace_activity
from change_operations.collapse_operation import collapse_operation
from change_operations.de_collapse_operation import decollapse_operation
from change_operations.modify_operation import modify_dependency
from change_operations.move_operation import move_activity
from change_operations.parallelize_operation import parallelize_activities
from change_operations.condition_update import condition_update
from utils.lock_dependencies_violations import locked_dependencies_preserved, get_violated_locked_dependencies

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'temp_uploads'
app.config['FREEZER_RELATIVE_URLS'] = True # Enable relative URLs for static files
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# BPMN Demo
BPMN_TRACES_PATH = os.path.join(os.path.dirname(__file__), 'sample-matrices', 'bpmn_traces.txt')
BPMN_LOCKS = [
    {'from': 'h', 'to': 'i', 'temporal': False, 'existential': True},
    {'from': 'h', 'to': 'j', 'temporal': False, 'existential': True},
    {'from': 'e', 'to': 'f', 'temporal': True, 'existential': False},
]

def load_bpmn_traces():
    with open(BPMN_TRACES_PATH, 'r') as f:
        traces = [line.strip().split(',') for line in f if line.strip()]
    return traces

def get_bpmn_matrix():
    traces = load_bpmn_traces()
    matrix = variants_to_matrix(traces)
    return matrix

def get_bpmn_locks():
    return BPMN_LOCKS

# DECLARE Demo
DECLARE_TRACES_PATH = os.path.join(os.path.dirname(__file__), 'sample-matrices', 'declare_traces.txt')
DECLARE_LOCKS = [
    {'from': 'e', 'to': 'f', 'temporal': False, 'existential': True},
    {'from': 'b', 'to': 'd', 'temporal': False, 'existential': True},
    {'from': 'a', 'to': 'b', 'temporal': True, 'existential': False},
]

def load_declare_traces():
    with open(DECLARE_TRACES_PATH, 'r') as f:
        traces = [line.strip().split(',') for line in f if line.strip()]
    return traces

def get_declare_matrix():
    traces = load_declare_traces()
    matrix = variants_to_matrix(traces)
    return matrix

def get_declare_locks():
    return DECLARE_LOCKS

# Hardcoded BPMN operations
BPMN_OPERATIONS = [
    {
        'id': 1,
        'title': 'Make e optional',
        'description': 'Make the execution of activity e optional, i.e., skip e.',
        'formal_input': {
            'operation': 'skip',
            'activity': 'e'
        }
    },
    {
        'id': 2,
        'title': 'Remove activity f',
        'description': 'Remove activity f.',
        'formal_input': {
            'operation': 'delete',
            'activity': 'f'
        }
    },
    {
        'id': 3,
        'title': 'Insert activity c',
        'description': 'Insert a new activity c so that the process ends as soon as c is executed. This means c is exclusive to any other activity after a.',
        'formal_input': {
            'operation': 'insert',
            'activity': 'c',
            'dependencies': [
                {'from': 'a', 'to': 'c', 'temporal': 'DIRECT', 'existential': 'IMPLICATION', 'existential_direction': 'BACKWARD'},
                {'from': 'b', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
                {'from': 'd', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
                {'from': 'e', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
                {'from': 'f', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
                {'from': 'g', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
                {'from': 'h', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
                {'from': 'i', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
                {'from': 'j', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'NAND'},
            ]
        }
    },
    {
        'id': 4,
        'title': 'Make h parallel to i',
        'description': 'Modify the relationship between activities h and i so that h is executed in parallel with i.',
        'formal_input': {
            'operation': 'modify',
            'from_activity': 'h',
            'to_activity': 'i',
            'temporal_dep': None,
            'existential_dep': 'EQUIVALENCE'
        }
    },
    {
        'id': 5,
        'title': 'Move h before b',
        'description': 'Move activity h before activity b so that h is executed directly after a and directly before b. However, h does not always have to follow a. The inclusive OR relationship between h and i, and h and j should not be changed, respectively.',
        'formal_input': {
            'operation': 'move',
            'activity': 'h',
            'dependencies': [
                {'from': 'h', 'to': 'b', 'temporal': 'DIRECT', 'existential': 'EQUIVALENCE'},
                {'from': 'a', 'to': 'h', 'temporal': 'DIRECT', 'existential': 'IMPLICATION', 'existential_direction': 'BACKWARD'},
                {'from': 'h', 'to': 'i', 'temporal': 'EVENTUAL', 'existential': 'OR'},
                {'from': 'h', 'to': 'j', 'temporal': 'EVENTUAL', 'existential': 'OR'},
            ]
        }
    }
]

# Hardcoded DECLARE operations
DECLARE_OPERATIONS = [
    {
        'id': 1,
        'title': 'Modify e-g relationship',
        'description': 'Modify the relationship between activities e and g so that whenever activity e occurs, activity g occurs as well, i.e., the existence of e implies the existence of g.',
        'formal_input': {
            'operation': 'modify',
            'from_activity': 'e',
            'to_activity': 'g',
            'temporal_dep': None,
            'existential_dep': 'IMPLICATION',
            'existential_direction': 'FORWARD'
        }
    },
    {
        'id': 2,
        'title': 'Remove activity f',
        'description': 'Remove activity f.',
        'formal_input': {
            'operation': 'delete',
            'activity': 'f'
        }
    },
    {
        'id': 3,
        'title': 'Move d before a',
        'description': 'Move activity d before a. This means, activity d has to occur before activity a now. However, activity a can still occur without activity d being executed.',
        'formal_input': {
            'operation': 'move',
            'activity': 'd',
            'dependencies': [
                {'from': 'b', 'to': 'd', 'temporal': 'INDEPENDENCE', 'existential': 'NEGATED_EQUIVALENCE'},
                {'from': 'd', 'to': 'a', 'temporal': 'EVENTUAL', 'existential': 'IMPLICATION', 'existential_direction': 'FORWARD'},
                {'from': 'd', 'to': 'e', 'temporal': 'INDEPENDENCE', 'existential': 'OR'},
                {'from': 'd', 'to': 'f', 'temporal': 'INDEPENDENCE', 'existential': 'OR'},
                {'from': 'd', 'to': 'g', 'temporal': 'INDEPENDENCE', 'existential': 'OR'},
                {'from': 'd', 'to': 'h', 'temporal': 'INDEPENDENCE', 'existential': 'INDEPENDENCE'},
                {'from': 'd', 'to': 'i', 'temporal': 'INDEPENDENCE', 'existential': 'INDEPENDENCE'},
            ]
        }
    },
    {
        'id': 4,
        'title': 'Insert activity c',
        'description': 'Insert a new activity c so that the execution of activity f leads to the execution of c before or after f. An occurrence of activity c implies an occurrence of a beforehand. An occurrence of activity b implies the occurrence of activity c afterward.',
        'formal_input': {
            'operation': 'insert',
            'activity': 'c',
            'dependencies': [
                {'from': 'a', 'to': 'c', 'temporal': 'EVENTUAL', 'existential': 'IMPLICATION', 'existential_direction': 'BACKWARD'},
                {'from': 'b', 'to': 'c', 'temporal': 'EVENTUAL', 'existential': 'IMPLICATION', 'existential_direction': 'FORWARD'},
                {'from': 'f', 'to': 'c', 'temporal': 'INDEPENDENCE', 'existential': 'IMPLICATION', 'existential_direction': 'FORWARD'},
            ]
        }
    },
    {
        'id': 5,
        'title': 'Make a optional',
        'description': 'Make the execution of activity a optional in any case, i.e., skip a.',
        'formal_input': {
            'operation': 'skip',
            'activity': 'a'
        }
    }
]

current_matrix = get_declare_matrix()
original_matrix = get_declare_matrix()
last_modified_matrix = None
@app.route("/api/bpmn_demo", methods=["GET"])
def bpmn_demo():
    """Return hardcoded BPMN change operations for demonstration."""
    return jsonify({
        "success": True,
        "operations": BPMN_OPERATIONS
    })

@app.route("/api/declare_demo", methods=["GET"])
def declare_demo():
    """Return hardcoded DECLARE change operations for demonstration."""
    return jsonify({
        "success": True,
        "operations": DECLARE_OPERATIONS
    })

@app.route("/api/load_bpmn_matrix", methods=["POST"])
def load_bpmn_matrix():
    """Load the BPMN demo matrix as the current matrix."""
    global current_matrix, original_matrix

    try:
        original_matrix = get_bpmn_matrix()
        current_matrix = copy.deepcopy(original_matrix)
        return jsonify({"success": True, "message": "BPMN matrix loaded successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/load_declare_matrix", methods=["POST"])
def load_declare_matrix():
    """Load the DECLARE demo matrix as the current matrix."""
    global current_matrix, original_matrix

    try:
        original_matrix = get_declare_matrix()
        current_matrix = copy.deepcopy(original_matrix)
        return jsonify({"success": True, "message": "DECLARE matrix loaded successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

def calculate_matrix_diff(original_matrix, modified_matrix):
    """Calculate differences between two matrices for highlighting purposes."""
    diff_info = {
        'added_activities': [],
        'removed_activities': [],
        'modified_cells': [],
        'added_cells': [],
        'removed_cells': []
    }

    if not original_matrix or not modified_matrix:
        return diff_info

    original_activities = set(original_matrix.activities)
    modified_activities = set(modified_matrix.activities)

    diff_info['added_activities'] = list(modified_activities - original_activities)
    diff_info['removed_activities'] = list(original_activities - modified_activities)

    common_activities = original_activities & modified_activities

    for from_activity in common_activities:
        for to_activity in common_activities:
            original_dep = original_matrix.get_dependency(from_activity, to_activity)
            modified_dep = modified_matrix.get_dependency(from_activity, to_activity)

            original_str = format_dependency_for_comparison(original_dep)
            modified_str = format_dependency_for_comparison(modified_dep)

            if original_str != modified_str:
                diff_info['modified_cells'].append((from_activity, to_activity))

    for activity in diff_info['added_activities']:
        for other_activity in modified_activities:
            if activity != other_activity:
                diff_info['added_cells'].append((activity, other_activity))
                diff_info['added_cells'].append((other_activity, activity))

    for activity in diff_info['removed_activities']:
        for other_activity in original_activities:
            if activity != other_activity:
                diff_info['removed_cells'].append((activity, other_activity))
                diff_info['removed_cells'].append((other_activity, activity))

    return diff_info

def format_dependency_for_comparison(dep_tuple):
    """Format dependency tuple for comparison purposes."""
    if not dep_tuple:
        return ""

    temporal_dep, existential_dep = dep_tuple

    is_temporal_independence = False
    temporal_str = "-"
    if temporal_dep:
        if temporal_dep.type == TemporalType.INDEPENDENCE:
            is_temporal_independence = True
        else:
            direction_symbol = "-"
            if temporal_dep.direction == Direction.FORWARD:
                direction_symbol = "≺"
            elif temporal_dep.direction == Direction.BACKWARD:
                direction_symbol = "≻"

            type_symbol = ""
            if temporal_dep.type == TemporalType.DIRECT:
                type_symbol = "d"

            temporal_str = f"{direction_symbol}{type_symbol}"

    is_existential_independence = False
    existential_str = "-"
    if existential_dep:
        if existential_dep.type == ExistentialType.INDEPENDENCE:
            is_existential_independence = True
        elif existential_dep.type == ExistentialType.IMPLICATION:
            if existential_dep.direction == Direction.FORWARD:
                existential_str = "=>"
            elif existential_dep.direction == Direction.BACKWARD:
                existential_str = "<="
        elif existential_dep.type == ExistentialType.EQUIVALENCE:
            existential_str = "⇔"
        elif existential_dep.type == ExistentialType.NEGATED_EQUIVALENCE:
            existential_str = "⇎"
        elif existential_dep.type == ExistentialType.NAND:
            existential_str = "⊼"
        elif existential_dep.type == ExistentialType.OR:
            existential_str = "∨"

    if is_temporal_independence and is_existential_independence:
        return "-,-"
    elif temporal_str != "-" or existential_str != "-":
        return f"{temporal_str},{existential_str}"
    else:
        return ""

def format_matrix_display(matrix, diff_info=None, is_original=False):
    """Format matrix display with optional diff highlighting."""
    if not matrix:
        return {"activities": [], "matrix": {}, "diff_info": {}}

    activities = sorted(matrix.activities)
    matrix_display = {}
    cell_classes = {}

    for from_activity in activities:
        matrix_display[from_activity] = {}
        cell_classes[from_activity] = {}

        for to_activity in activities:
            if from_activity == to_activity:
                matrix_display[from_activity][to_activity] = "X"
                cell_classes[from_activity][to_activity] = "diagonal"
                continue

            dep_tuple = matrix.get_dependency(from_activity, to_activity)
            if dep_tuple:
                temporal_dep, existential_dep = dep_tuple

                is_temporal_independence = False
                temporal_str = "-"
                if temporal_dep:
                    if temporal_dep.type == TemporalType.INDEPENDENCE:
                        is_temporal_independence = True
                    else:
                        direction_symbol = "-"
                        if temporal_dep.direction == Direction.FORWARD:
                            direction_symbol = "≺"
                        elif temporal_dep.direction == Direction.BACKWARD:
                            direction_symbol = "≻"

                        type_symbol = ""
                        if temporal_dep.type == TemporalType.DIRECT:
                            type_symbol = "d"

                        temporal_str = f"{direction_symbol}{type_symbol}"

                is_existential_independence = False
                existential_str = "-"
                if existential_dep:
                    if existential_dep.type == ExistentialType.INDEPENDENCE:
                        is_existential_independence = True
                    elif existential_dep.type == ExistentialType.IMPLICATION:
                        if existential_dep.direction == Direction.FORWARD:
                            existential_str = "=>"
                        elif existential_dep.direction == Direction.BACKWARD:
                            existential_str = "<="
                    elif existential_dep.type == ExistentialType.EQUIVALENCE:
                        existential_str = "⇔"
                    elif existential_dep.type == ExistentialType.NEGATED_EQUIVALENCE:
                        existential_str = "⇎"
                    elif existential_dep.type == ExistentialType.NAND:
                        existential_str = "⊼"
                    elif existential_dep.type == ExistentialType.OR:
                        existential_str = "∨"

                if is_temporal_independence and is_existential_independence:
                    matrix_display[from_activity][to_activity] = "-,-"
                elif temporal_str != "-" or existential_str != "-":
                    matrix_display[from_activity][to_activity] = f"{temporal_str},{existential_str}"
                else:
                    matrix_display[from_activity][to_activity] = ""
            else:
                matrix_display[from_activity][to_activity] = ""

            cell_class = ""
            if diff_info:
                if is_original:
                    if (from_activity, to_activity) in diff_info['removed_cells']:
                        cell_class = "diff-removed"
                    elif from_activity in diff_info['removed_activities'] or to_activity in diff_info['removed_activities']:
                        cell_class = "diff-removed-activity"
                else:
                    if (from_activity, to_activity) in diff_info['added_cells']:
                        cell_class = "diff-added"
                    elif (from_activity, to_activity) in diff_info['modified_cells']:
                        cell_class = "diff-modified"
                    elif from_activity in diff_info['added_activities'] or to_activity in diff_info['added_activities']:
                        cell_class = "diff-added-activity"

            cell_classes[from_activity][to_activity] = cell_class

    return {
        "activities": activities,
        "matrix": matrix_display,
        "cell_classes": cell_classes,
        "diff_info": diff_info or {}
    }

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/api/process", methods=["POST"])
def process_input():
    """Process either traces or a YAML file to generate an adjacency matrix."""
    global current_matrix, original_matrix

    try:
        if 'file' in request.files and request.files['file'].filename != '':
            file = request.files['file']
            if file and (file.filename.endswith('.yaml') or file.filename.endswith('.yml')):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)

                original_matrix = parse_yaml_to_adjacency_matrix(filepath)
                current_matrix = copy.deepcopy(original_matrix)

                os.remove(filepath) # Clean up the temporary file
            else:
                return jsonify({"success": False, "error": "Invalid file type. Please upload a YAML file."})

        else:
            data = request.get_json()
            traces = data.get('traces', [])
            if not traces:
                return jsonify({"success": False, "error": "No traces provided"})

            original_matrix = variants_to_matrix(traces)
            current_matrix = copy.deepcopy(original_matrix)

        return jsonify({"success": True, "message": "Matrix generated successfully."})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/matrix", methods=["GET"])
def get_matrix():
    """Return the current adjacency matrix."""
    if current_matrix is None:
        return jsonify({"success": False, "error": "Matrix not generated yet."})

    matrix_data = format_matrix_display(current_matrix)
    return jsonify({
        "success": True,
        "activities": matrix_data["activities"],
        "matrix": matrix_data["matrix"]
    })

@app.route("/api/change", methods=["POST"])
def change_matrix():
    """Perform a change operation on the current matrix."""
    global current_matrix, original_matrix, last_modified_matrix
    if original_matrix is None:
        return jsonify({"success": False, "error": "Matrix not generated yet."})

    # Determine which matrix to use as the source for the operation
    matrix_source = request.form.get('matrix_source', 'original')  # Default to original

    if matrix_source == 'modified':
        if last_modified_matrix is not None:
            current_matrix = copy.deepcopy(last_modified_matrix)
            source_matrix_for_diff = last_modified_matrix
        else:
            return jsonify({"success": False, "error": "No modified matrix available. Please perform an operation first or select 'Initial Matrix'."})
    else:
        current_matrix = copy.deepcopy(original_matrix)
        source_matrix_for_diff = original_matrix

    try:
        operation = request.form.get('operation')
        modified_matrix = None

        if operation == 'delete':
            activity = request.form.get('activity')
            modified_matrix = delete_activity(current_matrix, activity)
        elif operation == 'insert':
            activity = request.form.get('activity')

            dependencies = {}
            dependency_count = int(request.form.get('dependency_count', 0))

            for i in range(dependency_count):
                from_activity = request.form.get(f'from_activity_{i}')
                to_activity = request.form.get(f'to_activity_{i}')
                temporal_dep_str = request.form.get(f'temporal_dep_{i}')
                existential_dep_str = request.form.get(f'existential_dep_{i}')
                temporal_direction_str = request.form.get(f'temporal_direction_{i}')
                existential_direction_str = request.form.get(f'existential_direction_{i}')

                if from_activity and to_activity:
                    temporal_dep = None
                    existential_dep = None

                    if temporal_dep_str:
                        temporal_direction = Direction[temporal_direction_str] if temporal_direction_str else Direction.FORWARD
                        temporal_dep = TemporalDependency(TemporalType[temporal_dep_str], temporal_direction)

                    if existential_dep_str:
                        existential_direction = Direction[existential_direction_str] if existential_direction_str else Direction.FORWARD
                        existential_dep = ExistentialDependency(ExistentialType[existential_dep_str], existential_direction)

                    dependencies[(from_activity, to_activity)] = (temporal_dep, existential_dep)

            modified_matrix = insert_activity(current_matrix, activity, dependencies)
        elif operation == 'swap':
            activity1 = request.form.get('activity1')
            activity2 = request.form.get('activity2')
            modified_matrix = swap_activities(current_matrix, activity1, activity2)
        elif operation == 'skip':
            activity = request.form.get('activity_to_skip')
            modified_matrix = skip_activity(current_matrix, activity)
        elif operation == 'replace':
            old_activity = request.form.get('old_activity')
            new_activity = request.form.get('new_activity')
            modified_matrix = replace_activity(current_matrix, old_activity, new_activity)
        elif operation == 'collapse':
            collapsed_activity = request.form.get('collapsed_activity')
            collapse_activities = request.form.get('collapse_activities').split(',')
            modified_matrix = collapse_operation(current_matrix, collapsed_activity, collapse_activities)
        elif operation == 'de-collapse':
            collapsed_activity = request.form.get('collapsed_activity')

            if 'collapsed_matrix_file' not in request.files:
                return jsonify({"success": False, "error": "No collapsed matrix file provided."})

            file = request.files['collapsed_matrix_file']
            if file and (file.filename.endswith('.yaml') or file.filename.endswith('.yml')):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)

                collapsed_matrix = parse_yaml_to_adjacency_matrix(filepath)

                os.remove(filepath)
                modified_matrix = decollapse_operation(current_matrix, collapsed_activity, collapsed_matrix)
            else:
                return jsonify({"success": False, "error": "Invalid file type for collapsed matrix."})
        elif operation == 'modify':
            from_activity = request.form.get('from_activity')
            to_activity = request.form.get('to_activity')
            temporal_dep_str = request.form.get('temporal_dep')
            existential_dep_str = request.form.get('existential_dep')
            temporal_direction_str = request.form.get('temporal_direction')
            existential_direction_str = request.form.get('existential_direction')

            # Convert string parameters to enum types
            temporal_dep = None
            if temporal_dep_str:
                temporal_dep = TemporalType[temporal_dep_str]

            existential_dep = None
            if existential_dep_str:
                existential_dep = ExistentialType[existential_dep_str]

            temporal_direction = None
            if temporal_direction_str:
                temporal_direction = Direction[temporal_direction_str]

            existential_direction = None
            if existential_direction_str:
                existential_direction = Direction[existential_direction_str]

            modified_matrix = modify_dependency(current_matrix, from_activity, to_activity,
                                              temporal_dep, existential_dep,
                                              temporal_direction, existential_direction)
        elif operation == 'move':
            activity = request.form.get('activity')
            dependencies = {}
            dependency_count = int(request.form.get('dependency_count', 0))

            # Get locks to preserve locked dependencies
            locks = []
            try:
                locks = json.loads(request.form.get('locks', '[]'))
            except Exception:
                pass

            for i in range(dependency_count):
                from_activity = request.form.get(f'from_activity_{i}')
                to_activity = request.form.get(f'to_activity_{i}')
                temporal_dep_str = request.form.get(f'temporal_dep_{i}')
                existential_dep_str = request.form.get(f'existential_dep_{i}')
                temporal_direction_str = request.form.get(f'temporal_direction_{i}')
                existential_direction_str = request.form.get(f'existential_direction_{i}')

                if from_activity and to_activity:
                    temporal_dep = None
                    existential_dep = None

                    # Check if this dependency has locks
                    dependency_lock = None
                    for lock in locks:
                        if lock.get('from') == from_activity and lock.get('to') == to_activity:
                            dependency_lock = lock
                            break

                    # Get original dependency to preserve locked parts
                    orig_dep = current_matrix.get_dependency(from_activity, to_activity)
                    orig_temporal, orig_existential = orig_dep if orig_dep else (None, None)

                    if temporal_dep_str:
                        temporal_direction = Direction[temporal_direction_str] if temporal_direction_str else Direction.FORWARD
                        temporal_dep = TemporalDependency(TemporalType[temporal_dep_str], temporal_direction)
                    elif dependency_lock and dependency_lock.get('temporal') and orig_temporal:
                        temporal_dep = orig_temporal

                    if existential_dep_str:
                        existential_direction = Direction[existential_direction_str] if existential_direction_str else Direction.FORWARD
                        existential_dep = ExistentialDependency(ExistentialType[existential_dep_str], existential_direction)
                    elif dependency_lock and dependency_lock.get('existential') and orig_existential:
                        existential_dep = orig_existential

                    dependencies[(from_activity, to_activity)] = (temporal_dep, existential_dep)

            modified_matrix = move_activity(current_matrix, activity, dependencies)
        elif operation == 'parallelize':
            parallel_activities = set(request.form.get('parallel_activities').split(','))
            modified_matrix = parallelize_activities(current_matrix, parallel_activities)
        elif operation == 'condition_update':
            condition_activity = request.form.get('condition_activity')
            depending_activity = request.form.get('depending_activity')
            modified_matrix = condition_update(current_matrix, condition_activity, depending_activity)

        if modified_matrix:
            locks = []
            try:
                locks = json.loads(request.form.get('locks', '[]'))
            except Exception:
                pass

            locked_dependencies_dict = {}
            for lock in locks:
                frm = lock.get('from')
                to = lock.get('to')
                temporal_lock = lock.get('temporal', False)
                existential_lock = lock.get('existential', False)
                locked_dependencies_dict[(frm, to)] = (temporal_lock, existential_lock)

            if locked_dependencies_dict:
                if not locked_dependencies_preserved(
                    source_matrix_for_diff,
                    modified_matrix,
                    locked_dependencies_dict,
                    deletion_allowed=[]
                ):
                    violations = get_violated_locked_dependencies(
                        source_matrix_for_diff,
                        modified_matrix,
                        locked_dependencies_dict,
                        deletion_allowed=[]
                    )

                    error_messages = []
                    for (frm, to), (temp_violated, exist_violated) in violations.items():
                        if temp_violated and exist_violated:
                            error_messages.append(f"• {frm} → {to}: Both temporal and existential dependencies are locked and were violated")
                        elif temp_violated:
                            error_messages.append(f"• {frm} → {to}: Temporal dependency is locked and was violated")
                        elif exist_violated:
                            orig_dep = source_matrix_for_diff.get_dependency(frm, to)
                            if orig_dep:
                                _, orig_existential = orig_dep
                                if orig_existential and orig_existential.type.name == 'OR':
                                    error_messages.append(f"• {frm} → {to}: OR constraint violated (at least one must occur in all traces)")
                                else:
                                    error_messages.append(f"• {frm} → {to}: {orig_existential.type.name} constraint violated")
                            else:
                                error_messages.append(f"• {frm} → {to}: Existential dependency violated")

                    if len(error_messages) == 1:
                        error_msg = f"Operation violates locked dependency: {error_messages[0][2:]}"  # Remove bullet point
                    else:
                        error_msg = f"Operation violates {len(error_messages)} locked dependencies:\n" + "\n".join(error_messages)

                    return jsonify({"success": False, "error": error_msg})
            # Store the modified matrix for export
            last_modified_matrix = modified_matrix

            activities = modified_matrix.activities
            matrix_display = {}
            for from_activity in activities:
                matrix_display[from_activity] = {}
                for to_activity in activities:
                    if from_activity == to_activity:
                        matrix_display[from_activity][to_activity] = "X"
                        continue

                    dep_tuple = modified_matrix.get_dependency(from_activity, to_activity)
                    if dep_tuple:
                        temporal_dep, existential_dep = dep_tuple

                        is_temporal_independence = False
                        temporal_str = "-"
                        if temporal_dep:
                            if temporal_dep.type == TemporalType.INDEPENDENCE:
                                is_temporal_independence = True
                            else:
                                direction_symbol = "-"
                                if temporal_dep.direction == Direction.FORWARD:
                                    direction_symbol = "≺"
                                elif temporal_dep.direction == Direction.BACKWARD:
                                    direction_symbol = "≻"

                                type_symbol = ""
                                if temporal_dep.type == TemporalType.DIRECT:
                                    type_symbol = "d"

                                temporal_str = f"{direction_symbol}{type_symbol}"

                        is_existential_independence = False
                        existential_str = "-"
                        if existential_dep:
                            if existential_dep.type == ExistentialType.INDEPENDENCE:
                                is_existential_independence = True
                            elif existential_dep.type == ExistentialType.IMPLICATION:
                                if existential_dep.direction == Direction.FORWARD:
                                    existential_str = "=>"
                                elif existential_dep.direction == Direction.BACKWARD:
                                    existential_str = "<="
                            elif existential_dep.type == ExistentialType.EQUIVALENCE:
                                existential_str = "⇔"
                            elif existential_dep.type == ExistentialType.NEGATED_EQUIVALENCE:
                                existential_str = "⇎"
                            elif existential_dep.type == ExistentialType.NAND:
                                existential_str = "⊼"
                            elif existential_dep.type == ExistentialType.OR:
                                existential_str = "∨"

                        if is_temporal_independence and is_existential_independence:
                            matrix_display[from_activity][to_activity] = "-,-"
                        elif temporal_str != "-" or existential_str != "-":
                            matrix_display[from_activity][to_activity] = f"{temporal_str},{existential_str}"
                        else:
                            matrix_display[from_activity][to_activity] = ""
                    else:
                        matrix_display[from_activity][to_activity] = ""

            diff_info = calculate_matrix_diff(source_matrix_for_diff, modified_matrix)
            formatted_source = format_matrix_display(source_matrix_for_diff, diff_info, is_original=True)
            formatted_modified = format_matrix_display(modified_matrix, diff_info, is_original=False)

            last_modified_matrix = modified_matrix

            return jsonify({
                "success": True,
                "original": {
                    "activities": formatted_source["activities"],
                    "matrix": formatted_source["matrix"],
                    "cell_classes": formatted_source["cell_classes"]
                },
                "modified": {
                    "activities": formatted_modified["activities"],
                    "matrix": formatted_modified["matrix"],
                    "cell_classes": formatted_modified["cell_classes"]
                },
                "diff_info": diff_info
            })
        else:
            return jsonify({"success": False, "error": "Operation not supported or failed."})

    except AttributeError as e:
        error_msg = str(e)
        if "'NoneType' object has no attribute" in error_msg:
            return jsonify({
                "success": False,
                "error": "Invalid operation: Cannot modify this relationship. The operation would create an invalid process model. Please check that the specified dependencies are compatible with the current process structure."
            })
        return jsonify({"success": False, "error": f"Attribute error: {error_msg}"})
    except ValueError as e:
        # ValueError typically contains useful user-facing messages from operations
        return jsonify({"success": False, "error": str(e)})
    except KeyError as e:
        # KeyError when enum conversion fails or activities not found
        return jsonify({"success": False, "error": f"Invalid value: {e}. Please check that all activities and dependency types are valid."})
    except Exception as e:
        # Generic catch-all for unexpected errors
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/export", methods=["GET"])
def export_matrix():
    """Export the last modified matrix as YAML."""
    global last_modified_matrix

    if last_modified_matrix is None:
        return jsonify({"success": False, "error": "No modified matrix available to export."})

    try:
        sorted_activities = sorted(last_modified_matrix.activities)
        yaml_data = {
            "metadata": {
                "format_version": "1.0",
                "description": "Process adjacency matrix with temporal and existential dependencies",
                "activities": sorted_activities
            },
            "dependencies": []
        }

        for from_activity in sorted_activities:
            for to_activity in sorted_activities:
                if from_activity != to_activity:
                    dep_tuple = last_modified_matrix.get_dependency(from_activity, to_activity)
                    if dep_tuple:
                        temporal_dep, existential_dep = dep_tuple

                        # Only add non-empty dependencies
                        if temporal_dep or existential_dep:
                            dependency_entry = {
                                "from": from_activity,
                                "to": to_activity
                            }

                            if temporal_dep:
                                temp_type = temporal_dep.type.name.lower()
                                temp_direction = temporal_dep.direction.name.lower()

                                if temporal_dep.type == TemporalType.INDEPENDENCE:
                                    symbol = "-"
                                    direction = "both"
                                elif temporal_dep.type == TemporalType.DIRECT:
                                    symbol = "≺_d"
                                    direction = temp_direction
                                else:
                                    symbol = "≺_e"
                                    direction = temp_direction

                                dependency_entry["temporal"] = {
                                    "type": temp_type,
                                    "symbol": symbol,
                                    "direction": direction
                                }

                            if existential_dep:
                                exist_type = existential_dep.type.name.lower()
                                exist_direction = existential_dep.direction.name.lower()

                                if existential_dep.type == ExistentialType.INDEPENDENCE:
                                    symbol = "-"
                                    direction = "both"
                                elif existential_dep.type == ExistentialType.IMPLICATION:
                                    symbol = "⇒"
                                    direction = exist_direction
                                elif existential_dep.type == ExistentialType.EQUIVALENCE:
                                    symbol = "⇔"
                                    direction = "both"
                                elif existential_dep.type == ExistentialType.NEGATED_EQUIVALENCE:
                                    symbol = "⇎"
                                    direction = "both"
                                elif existential_dep.type == ExistentialType.NAND:
                                    symbol = "|"
                                    direction = "both"
                                elif existential_dep.type == ExistentialType.OR:
                                    symbol = "∨"
                                    direction = "both"
                                else:
                                    symbol = "-"
                                    direction = "both"

                                dependency_entry["existential"] = {
                                    "type": exist_type,
                                    "symbol": symbol,
                                    "direction": direction
                                }

                            yaml_data["dependencies"].append(dependency_entry)

        yaml_string = yaml.dump(yaml_data, default_flow_style=False, sort_keys=False,
                               allow_unicode=True, encoding=None)

        return jsonify({
            "success": True,
            "yaml_data": yaml_string,
            "filename": "matrix.yaml"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    app.run(debug=True)
