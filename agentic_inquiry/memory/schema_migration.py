"""Memory table schema migration utilities.

Handles schema validation and migration for memory tables when embedding
dimensions change.
"""

import logging
from pathlib import Path

import pyarrow as pa


logger = logging.getLogger(__name__)


class SchemaValidator:
    """Validates and migrates memory table schemas."""

    @staticmethod
    def validate_schema(
        expected_schema: pa.Schema,
        table_name: str,
        db_path: Path,
    ) -> bool:
        """Validate that a table's schema matches expected schema.

        Args:
            expected_schema: Expected PyArrow schema
            table_name: Name of the table to validate
            db_path: Path to LanceDB database

        Returns:
            True if schema matches, False if mismatch or table doesn't exist
        """
        try:
            import lancedb

            # Connect to database
            db = lancedb.connect(str(db_path))

            # Check if table exists
            table_names = db.table_names()
            if table_name not in table_names:
                logger.debug("Table '%s' does not exist yet", table_name)
                return False

            # Get existing schema
            table = db.open_table(table_name)
            existing_schema = table.schema

            # Compare critical vector fields
            critical_fields = ["vector", "summary_vector"]
            for field_name in critical_fields:
                if field_name not in expected_schema.names:
                    continue

                expected_field = expected_schema.field(field_name)
                if field_name not in existing_schema.names:
                    logger.warning(
                        "Field '%s' missing from table '%s'",
                        field_name,
                        table_name,
                    )
                    return False

                existing_field = existing_schema.field(field_name)

                # Check if dimensions match
                if not SchemaValidator._fields_match(expected_field, existing_field):
                    logger.warning(
                        "Schema mismatch in table '%s' field '%s': expected %s, got %s",
                        table_name,
                        field_name,
                        expected_field.type,
                        existing_field.type,
                    )
                    return False

            logger.debug("Schema validation passed for table '%s'", table_name)
            return True

        except Exception as e:
            logger.warning(
                "Error validating schema for table '%s': %s",
                table_name,
                e,
            )
            return False

    @staticmethod
    def _fields_match(field1: pa.Field, field2: pa.Field) -> bool:
        """Check if two PyArrow fields have matching types.

        Args:
            field1: First field to compare
            field2: Second field to compare

        Returns:
            True if field types match
        """
        # For FixedSizeList types, check list size matches
        if isinstance(field1.type, pa.FixedSizeListType) and isinstance(
            field2.type, pa.FixedSizeListType
        ):
            return field1.type.list_size == field2.type.list_size

        # For other types, use equality
        return field1.type == field2.type

    @staticmethod
    def drop_table_if_schema_mismatch(
        expected_schema: pa.Schema,
        table_name: str,
        db_path: Path,
    ) -> bool:
        """Drop a table if its schema doesn't match expected schema.

        Args:
            expected_schema: Expected PyArrow schema
            table_name: Name of the table to validate and potentially drop
            db_path: Path to LanceDB database

        Returns:
            True if table was dropped, False if no action needed
        """
        try:
            # Validate schema
            schema_valid = SchemaValidator.validate_schema(
                expected_schema,
                table_name,
                db_path,
            )

            if schema_valid:
                # Schema is valid, no action needed
                return False

            # Schema is invalid or table doesn't exist - check if we need to drop
            import lancedb

            db = lancedb.connect(str(db_path))
            table_names = db.table_names()

            if table_name not in table_names:
                # Table doesn't exist, no need to drop
                logger.debug("Table '%s' does not exist, no need to drop", table_name)
                return False

            # Schema mismatch - drop the table
            logger.warning(
                "Dropping table '%s' due to schema mismatch (will be recreated with correct schema)",
                table_name,
            )

            # LanceDB doesn't have direct drop_table, so we need to use the database's method
            # For LanceDB, we can delete the table directory
            table_path = db_path / f"{table_name}.lance"
            if table_path.exists():
                import shutil
                shutil.rmtree(table_path)
                logger.info("Dropped table '%s'", table_name)
                return True

            return False

        except Exception as e:
            logger.error(
                "Error dropping table '%s': %s",
                table_name,
                e,
                exc_info=True,
            )
            return False

    @staticmethod
    def ensure_schema_compatible(
        expected_schema: pa.Schema,
        table_name: str,
        db_path: Path,
        auto_drop: bool = True,
    ) -> bool:
        """Ensure table schema is compatible, optionally dropping incompatible tables.

        Args:
            expected_schema: Expected PyArrow schema
            table_name: Name of the table to validate
            db_path: Path to LanceDB database
            auto_drop: Whether to automatically drop incompatible tables (default: True)

        Returns:
            True if schema is compatible (or was made compatible), False otherwise
        """
        schema_valid = SchemaValidator.validate_schema(
            expected_schema,
            table_name,
            db_path,
        )

        if schema_valid:
            return True

        if not auto_drop:
            logger.warning(
                "Schema mismatch for table '%s' (auto_drop=False)",
                table_name,
            )
            return False

        # Auto-drop enabled - drop incompatible table
        was_dropped = SchemaValidator.drop_table_if_schema_mismatch(
            expected_schema,
            table_name,
            db_path,
        )

        if was_dropped:
            logger.info(
                "Table '%s' will be recreated with correct schema on next insert",
                table_name,
            )
            return True

        # Table doesn't exist yet or couldn't be dropped
        return True
