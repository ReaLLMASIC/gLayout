#!/bin/bash

# ==============================================================================
# Deep Rename Script
#
# Description:
#   This script renames a top-level directory, recursively renames any files
#   inside it that share the original directory's name, and then finds and
#   replaces all occurrences of the original name within the content of all
#   text files in the new directory.
#
# Usage:
#   ./deep_rename.sh <original_name> <new_name> [--dry-run]
#
# Arguments:
#   <original_name>: The name of the folder you want to rename.
#   <new_name>:      The new name for the folder and its related files/content.
#   --dry-run (optional): If provided, the script will only print the actions
#                         it would take without executing them.
#
# Example:
#   ./deep_rename.sh circuit_to_live circuit_to_die
#
# Example Dry Run:
#   ./deep_rename.sh circuit_to_live circuit_to_die --dry-run
#
# ==============================================================================

# --- Configuration and Argument Handling ---

ORIGINAL_NAME="$1"
NEW_NAME="$2"
DRY_RUN_FLAG="$3"
DRY_RUN=false

# Check if this is a dry run
if [[ "$DRY_RUN_FLAG" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[INFO] DRY RUN MODE ENABLED. No files or folders will be changed."
fi

# --- Sanity Checks ---

# Check if the correct number of arguments was provided
if [ -z "$ORIGINAL_NAME" ] || [ -z "$NEW_NAME" ]; then
    echo "ERROR: Missing arguments."
    echo "Usage: $0 <original_name> <new_name> [--dry-run]"
    exit 1
fi

# Check if the original directory exists
if [ ! -d "$ORIGINAL_NAME" ]; then
    echo "ERROR: The source directory '$ORIGINAL_NAME' does not exist."
    exit 1
fi

# Check if a file or directory with the new name already exists
if [ -e "$NEW_NAME" ]; then
    echo "ERROR: A file or directory named '$NEW_NAME' already exists in this location. Aborting."
    exit 1
fi

# --- Main Logic ---

echo "------------------------------------------------------------------"
echo "Deep Rename Plan:"
echo "  - Top-level folder: '$ORIGINAL_NAME' -> '$NEW_NAME'"
echo "  - Files inside matching '$ORIGINAL_NAME.*' will be renamed to '$NEW_NAME.*'"
echo "  - Text content inside all files will be changed from '$ORIGINAL_NAME' to '$NEW_NAME'"
echo "------------------------------------------------------------------"

# Confirmation prompt before proceeding (unless it's a dry run)
if [ "$DRY_RUN" = false ]; then
    read -p "Are you sure you want to proceed? (yes/no): " confirmation
    if [[ "$confirmation" != "yes" ]]; then
        echo "Aborted by user."
        exit 0
    fi
fi

# --- Step 1: Find all matching files and prepare for rename ---
# We do this *before* renaming the top-level folder to make finding the files easier.

echo "[INFO] Searching for files to rename..."
# Use find to locate all files matching the pattern and store them in an array
# -print0 and read -d '' handle filenames with spaces or special characters
files_to_rename=()
while IFS= read -r -d '' file; do
    files_to_rename+=("$file")
done < <(find "$ORIGINAL_NAME" -type f -name "$ORIGINAL_NAME.*" -print0)

# --- Step 2: Rename the top-level folder ---

echo "[ACTION] Renaming top-level folder..."
if [ "$DRY_RUN" = true ]; then
    echo "  [DRY RUN] Would rename folder '$ORIGINAL_NAME' to '$NEW_NAME'."
else
    mv "$ORIGINAL_NAME" "$NEW_NAME"
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to rename the top-level folder. Aborting."
        exit 1
    fi
    echo "  - Success: Renamed '$ORIGINAL_NAME' to '$NEW_NAME'."
fi

# --- Step 3: Recursively rename the found files ---

echo "[ACTION] Renaming internal files..."
if [ ${#files_to_rename[@]} -eq 0 ]; then
    echo "  - No files matching '$ORIGINAL_NAME.*' were found inside."
else
    for old_path in "${files_to_rename[@]}"; do
        # Construct the new path by replacing the top-level folder name in the path string
        # This is more robust than just replacing the filename part
        new_path=$(echo "$old_path" | sed "s#^$ORIGINAL_NAME/#$NEW_NAME/#" | sed "s/\/$ORIGINAL_NAME\./\/$NEW_NAME\./")

        if [ "$DRY_RUN" = true ]; then
            # In dry run, the top-level folder wasn't actually renamed, so we simulate the new path
            echo "  [DRY RUN] Would rename file '$old_path' to '$new_path'."
        else
            # In a real run, the path has already partially changed due to the top-level folder rename.
            # We need to reference the path inside the *newly renamed* folder.
            path_in_new_folder=$(echo "$old_path" | sed "s#^$ORIGINAL_NAME/#$NEW_NAME/#")
            
            # The final destination path is the same 'new_path' calculated earlier
            mv "$path_in_new_folder" "$new_path"
            if [ $? -eq 0 ]; then
                echo "  - Success: Renamed '$path_in_new_folder' to '$new_path'."
            else
                echo "  - ERROR: Failed to rename '$path_in_new_folder'."
            fi
        fi
    done
fi

# --- Step 4: Find and Replace content in files ---

echo "[ACTION] Replacing content in all text files..."
# The directory to search in depends on whether this is a dry run or not
search_dir="$NEW_NAME"
if [ "$DRY_RUN" = true ]; then
    search_dir="$ORIGINAL_NAME"
fi

# Find all text files containing the original name string
# grep -rlI: recursive, list-filenames, ignore-binary-files
# -Z and -print0 handle all filenames safely
files_to_modify_content=()
while IFS= read -r -d '' file; do
    files_to_modify_content+=("$file")
done < <(grep -rlIZ "$ORIGINAL_NAME" "$search_dir" 2>/dev/null)

if [ ${#files_to_modify_content[@]} -eq 0 ]; then
    echo "  - No text files with content matching '$ORIGINAL_NAME' were found."
else
    for file_path in "${files_to_modify_content[@]}"; do
        if [ "$DRY_RUN" = true ]; then
            # Count occurrences for the dry run report
            count=$(grep -o "$ORIGINAL_NAME" "$file_path" | wc -l)
            echo "  [DRY RUN] Would replace $count occurrence(s) of '$ORIGINAL_NAME' in file '$file_path'."
        else
            # Use sed for in-place replacement. Using # as a delimiter is safer
            # if names contain slashes.
            sed -i "s#$ORIGINAL_NAME#$NEW_NAME#g" "$file_path"
            if [ $? -eq 0 ]; then
                echo "  - Success: Replaced content in '$file_path'."
            else
                echo "  - ERROR: Failed to replace content in '$file_path'."
            fi
        fi
    done
fi

echo "------------------------------------------------------------------"
echo "[INFO] Script finished."
echo "------------------------------------------------------------------"

exit 0
