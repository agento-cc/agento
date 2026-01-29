class SeedDefaults:
    """Example data patch — seeds default config values."""

    def apply(self, conn):
        # Insert default data here, e.g.:
        # with conn.cursor() as cur:
        #     cur.execute("INSERT IGNORE INTO ...")
        # conn.commit()
        pass

    def require(self):
        # Return fully-qualified patch names that must run first:
        # e.g. ["other_module/SetupBaseTables"]
        return []
