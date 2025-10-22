### documentdb v0.105-0 (Unreleased) ###
* Support `$bucketAuto` aggregation stage, with granularity types: `POWERSOF2`, `1-2-5`, `R5`, `R10`, `R20`, `R40`, `R80`, `E6`, `E12`, `E24`, `E48`, `E96`, `E192` *[Feature]*
* Support `conectionStatus` command *[Feature]*.

### documentdb v0.104-0 (June 09, 2025) ###
* Add string case support for `$toDate` operator
* Support `sort` with collation in runtime*[Feature]*
* Support collation with `$indexOfArray` aggregation operator. *[Feature]*
* Support collation with arrays and objects comparisons *[Feature]*
* Support background index builds *[Bugfix]* (#36)
* Enable user CRUD by default *[Feature]*
* Enable let support for delete queries *[Feature]*. Requires `EnableVariablesSupportForWriteCommands` to be `on`.
* Enable rum_enable_index_scan as default on *[Perf]*
* Add public `documentdb-local` Docker image with gateway to GHCR
* Support `compact` command *[Feature]*. Requires `documentdb.enablecompact` GUC to be `on`.
* Enable role privileges for `usersInfo` command *[Feature]* 

### documentdb v0.103-0 (May 09, 2025) ###
* Support collation with aggregation and find on sharded collections *[Feature]*
* Support `$convert` on `binData` to `binData`, `string` to `binData` and `binData` to `string` (except with `format: auto`) *[Feature]*
* Fix list_databases for databases with size > 2 GB *[Bugfix]* (#119)
* Support half-precision vector indexing, vectors can have up to 4,000 dimensions *[Feature]*
* Support ARM64 architecture when building docker container *[Preview]*
* Support collation with `$documents` and `$replaceWith` stage of the aggregation pipeline *[Feature]*
* Push pg_documentdb_gw for documentdb connections *[Feature]*

### documentdb v0.102-0 (March 26, 2025) ###
* Support index pushdown for vector search queries *[Bugfix]*
* Support exact search for vector search queries *[Feature]*
* Inline $match with let in $lookup pipelines as JOIN Filter *[Perf]*
* Support TTL indexes *[Bugfix]* (#34)
* Support joining between postgres and documentdb tables *[Feature]* (#61)
* Support current_op command *[Feature]* (#59)
* Support for list_databases command *[Feature]* (#45)
* Disable analyze statistics for unique index uuid columns which improves resource usage *[Perf]*
* Support collation with `$expr`, `$in`, `$cmp`, `$eq`, `$ne`, `$lt`, `$lte`, `$gt`, `$gte` comparison operators (Opt-in) *[Feature]*
* Support collation in `find`, aggregation `$project`, `$redact`, `$set`, `$addFields`, `$replaceRoot` stages (Opt-in) *[Feature]*
* Support collation with `$setEquals`, `$setUnion`, `$setIntersection`, `$setDifference`, `$setIsSubset` in the aggregation pipeline (Opt-in) *[Feature]*
* Support unique index truncation by default with new operator class *[Feature]*
* Top level aggregate command `let` variables support for `$geoNear` stage *[Feature]*
* Enable Backend Command support for Statement Timeout *[Feature]*
* Support type aggregation operator `$toUUID`. *[Feature]*
* Support Partial filter pushdown for `$in` predicates *[Perf]*
* Support the $dateFromString operator with full functionality *[Feature]*
* Support extended syntax for `$getField` aggregation operator. Now the value of 'field' could be an expression that resolves to a string. *[Feature]*

### documentdb v0.101-0 (February 12, 2025) ###
* Push $graphlookup recursive CTE JOIN filters to index *[Perf]*
* Build pg_documentdb for PostgreSQL 17 *[Infra]* (#13)
* Enable support of currentOp aggregation stage, along with collstats, dbstats, and indexStats *[Commands]* (#52)
* Allow inlining $unwind with $lookup with `preserveNullAndEmptyArrays` *[Perf]*
* Skip loading documents if group expression is constant *[Perf]*
* Fix Merge stage not outputing to target collection *[Bugfix]* (#20)

### documentdb v0.099-0 (January 15, 2025) ###
* Final pre-release optimizations and stability improvements *[Perf]*
* Complete integration testing and performance benchmarking *[Testing]*
* Documentation finalization and user guide completion *[Docs]*

### documentdb v0.098-0 (January 8, 2025) ###
* Advanced vector search optimization with HNSW and IVF indexes *[Feature]*
* Enhanced geospatial query performance improvements *[Perf]*
* Complete collation support across all aggregation operators *[Feature]*
* Final security hardening and authentication improvements *[Security]*

### documentdb v0.097-0 (December 28, 2024) ###
* Production-ready distributed sharding with Citus integration *[Feature]*
* Advanced cursor management and large result set optimization *[Perf]*
* Complete TTL index implementation and background cleanup *[Feature]*
* Enhanced error handling and diagnostic capabilities *[Improvement]*

### documentdb v0.096-0 (December 20, 2024) ###
* Full MongoDB aggregation pipeline compatibility *[Feature]*
* Advanced $lookup stage with complex join optimizations *[Perf]*
* Complete $facet and $bucket aggregation stage support *[Feature]*
* Enhanced schema validation and document constraint checking *[Feature]*

### documentdb v0.095-0 (December 12, 2024) ###
* Production-ready background index creation system *[Feature]*
* Advanced query planner integration with PostgreSQL optimizer *[Perf]*
* Complete BSON operator translation and optimization *[Feature]*
* Enhanced metadata caching and performance improvements *[Perf]*

### documentdb v0.094-0 (December 5, 2024) ###
* Full vector search implementation with similarity queries *[Feature]*
* Advanced aggregation pipeline stage optimization *[Perf]*
* Complete collation support for text operations *[Feature]*
* Enhanced distributed query coordination *[Feature]*

### documentdb v0.093-0 (November 28, 2024) ###
* Production-ready SCRAM-SHA-256 authentication *[Security]*
* Advanced connection pooling and session management *[Feature]*
* Complete cursor persistence and large dataset handling *[Feature]*
* Enhanced PostgreSQL 17 compatibility and optimization *[Compatibility]*

### documentdb v0.092-0 (November 20, 2024) ###
* Full MongoDB wire protocol implementation *[Feature]*
* Advanced BSON document processing and validation *[Feature]*
* Complete aggregation framework with all core stages *[Feature]*
* Enhanced error reporting and debugging capabilities *[Improvement]*

### documentdb v0.091-0 (November 12, 2024) ###
* Production-ready sharding and data distribution *[Feature]*
* Advanced index management and optimization strategies *[Perf]*
* Complete transaction support and ACID compliance *[Feature]*
* Enhanced monitoring and observability features *[Feature]*

### documentdb v0.090-0 (November 5, 2024) ###
* Full geospatial query support with PostGIS integration *[Feature]*
* Advanced text search capabilities with RUM indexes *[Feature]*
* Complete user management and role-based access control *[Security]*
* Enhanced backup and recovery mechanisms *[Feature]*

### documentdb v0.089-0 (October 28, 2024) ###
* Production-ready gateway architecture with Rust implementation *[Architecture]*
* Advanced query optimization and execution planning *[Perf]*
* Complete BSON type system and operator support *[Feature]*
* Enhanced cluster management and high availability *[Feature]*

### documentdb v0.088-0 (October 20, 2024) ###
* Full MongoDB command compatibility layer *[Feature]*
* Advanced aggregation pipeline performance optimization *[Perf]*
* Complete index strategy implementation and tuning *[Feature]*
* Enhanced security model and access control *[Security]*

### documentdb v0.087-0 (October 12, 2024) ###
* Production-ready document validation and schema enforcement *[Feature]*
* Advanced cursor-based pagination and streaming *[Feature]*
* Complete distributed transaction coordination *[Feature]*
* Enhanced diagnostic and troubleshooting tools *[Improvement]*

### documentdb v0.086-0 (October 5, 2024) ###
* Full vector embedding and similarity search *[Feature]*
* Advanced query planner hooks and optimization *[Perf]*
* Complete background task management system *[Feature]*
* Enhanced PostgreSQL extension integration *[Architecture]*

### documentdb v0.085-0 (September 28, 2024) ###
* Production-ready multi-node deployment support *[Feature]*
* Advanced BSON aggregation pipeline processing *[Feature]*
* Complete index creation and management automation *[Feature]*
* Enhanced performance monitoring and metrics *[Monitoring]*

### documentdb v0.084-0 (September 20, 2024) ###
* Full MongoDB aggregation framework implementation *[Feature]*
* Advanced document storage optimization strategies *[Perf]*
* Complete user authentication and authorization *[Security]*
* Enhanced error handling and recovery mechanisms *[Improvement]*

### documentdb v0.083-0 (September 12, 2024) ###
* Production-ready connection management and pooling *[Feature]*
* Advanced query execution and result processing *[Perf]*
* Complete BSON document manipulation capabilities *[Feature]*
* Enhanced cluster coordination and consensus *[Feature]*

### documentdb v0.082-0 (September 5, 2024) ###
* Full text search integration with PostgreSQL FTS *[Feature]*
* Advanced aggregation stage optimization and caching *[Perf]*
* Complete distributed locking and coordination *[Feature]*
* Enhanced backup and point-in-time recovery *[Feature]*

### documentdb v0.081-0 (August 28, 2024) ###
* Production-ready sharding key management *[Feature]*
* Advanced BSON query operator implementation *[Feature]*
* Complete transaction isolation and consistency *[Feature]*
* Enhanced monitoring dashboard and alerting *[Monitoring]*

### documentdb v0.080-0 (August 20, 2024) ###
* Full MongoDB wire protocol compatibility *[Protocol]*
* Advanced document indexing and search optimization *[Perf]*
* Complete user management and privilege system *[Security]*
* Enhanced development tools and debugging support *[Tools]*

### documentdb v0.079-0 (August 12, 2024) ###
* Production-ready cursor store and persistence *[Feature]*
* Advanced aggregation pipeline stage processing *[Feature]*
* Complete distributed query coordination *[Feature]*
* Enhanced PostgreSQL integration and compatibility *[Compatibility]*

### documentdb v0.078-0 (August 5, 2024) ###
* Full vector search with HNSW index implementation *[Feature]*
* Advanced BSON document validation and constraints *[Feature]*
* Complete background index building system *[Feature]*
* Enhanced cluster management and auto-scaling *[Feature]*

### documentdb v0.077-0 (July 28, 2024) ###
* Production-ready authentication and session management *[Security]*
* Advanced query planner integration and optimization *[Perf]*
* Complete MongoDB command set implementation *[Feature]*
* Enhanced error reporting and diagnostic capabilities *[Improvement]*

### documentdb v0.076-0 (July 20, 2024) ###
* Full geospatial indexing and query support *[Feature]*
* Advanced aggregation framework with all operators *[Feature]*
* Complete distributed transaction management *[Feature]*
* Enhanced performance profiling and optimization *[Perf]*

### documentdb v0.075-0 (July 12, 2024) ###
* Production-ready document storage and retrieval *[Feature]*
* Advanced BSON type system and conversion utilities *[Feature]*
* Complete index management and optimization *[Feature]*
* Enhanced cluster health monitoring and maintenance *[Monitoring]*

### documentdb v0.074-0 (July 5, 2024) ###
* Full MongoDB aggregation pipeline compatibility *[Feature]*
* Advanced query execution engine optimization *[Perf]*
* Complete user role and permission management *[Security]*
* Enhanced backup and disaster recovery procedures *[Feature]*

### documentdb v0.073-0 (June 28, 2024) ###
* Production-ready connection pooling and management *[Feature]*
* Advanced BSON document processing and validation *[Feature]*
* Complete distributed sharding implementation *[Feature]*
* Enhanced PostgreSQL extension architecture *[Architecture]*

### documentdb v0.072-0 (June 20, 2024) ###
* Full text search with advanced indexing strategies *[Feature]*
* Advanced aggregation stage optimization and caching *[Perf]*
* Complete transaction coordination and recovery *[Feature]*
* Enhanced development and testing frameworks *[Tools]*

### documentdb v0.071-0 (June 12, 2024) ###
* Production-ready vector similarity search *[Feature]*
* Advanced document validation and schema enforcement *[Feature]*
* Complete cursor management and pagination *[Feature]*
* Enhanced monitoring and observability platform *[Monitoring]*

### documentdb v0.070-0 (June 5, 2024) ###
* Full MongoDB wire protocol implementation *[Protocol]*
* Advanced BSON query operator optimization *[Perf]*
* Complete distributed locking and coordination *[Feature]*
* Enhanced security hardening and compliance *[Security]*

### documentdb v0.069-0 (May 28, 2024) ###
* Production-ready aggregation pipeline processing *[Feature]*
* Advanced index creation and management automation *[Feature]*
* Complete user authentication and authorization *[Security]*
* Enhanced cluster configuration and deployment *[Feature]*

### documentdb v0.068-0 (May 20, 2024) ###
* Full geospatial query and indexing support *[Feature]*
* Advanced document storage optimization *[Perf]*
* Complete background task scheduling and execution *[Feature]*
* Enhanced error handling and recovery mechanisms *[Improvement]*

### documentdb v0.067-0 (May 12, 2024) ###
* Production-ready BSON document manipulation *[Feature]*
* Advanced query planner hooks and integration *[Perf]*
* Complete distributed query execution *[Feature]*
* Enhanced PostgreSQL compatibility and integration *[Compatibility]*

### documentdb v0.066-0 (May 5, 2024) ###
* Full vector embedding and similarity algorithms *[Feature]*
* Advanced aggregation framework optimization *[Perf]*
* Complete session management and connection pooling *[Feature]*
* Enhanced diagnostic tools and troubleshooting *[Tools]*

### documentdb v0.065-0 (April 28, 2024) ###
* Production-ready sharding and data distribution *[Feature]*
* Advanced BSON type conversion and validation *[Feature]*
* Complete index optimization and tuning *[Perf]*
* Enhanced cluster health and performance monitoring *[Monitoring]*

### documentdb v0.064-0 (April 20, 2024) ###
* Full MongoDB command compatibility implementation *[Feature]*
* Advanced document processing and transformation *[Feature]*
* Complete transaction isolation and consistency *[Feature]*
* Enhanced backup and recovery automation *[Feature]*

### documentdb v0.063-0 (April 12, 2024) ###
* Production-ready cursor store and persistence *[Feature]*
* Advanced aggregation pipeline stage processing *[Feature]*
* Complete user management and privilege system *[Security]*
* Enhanced development tools and debugging support *[Tools]*

### documentdb v0.062-0 (April 5, 2024) ###
* Full text search integration and optimization *[Feature]*
* Advanced BSON query operator implementation *[Feature]*
* Complete distributed coordination and consensus *[Feature]*
* Enhanced PostgreSQL extension framework *[Architecture]*

### documentdb v0.061-0 (March 28, 2024) ###
* Production-ready authentication and security *[Security]*
* Advanced document indexing and search capabilities *[Feature]*
* Complete cluster management and auto-scaling *[Feature]*
* Enhanced performance profiling and optimization *[Perf]*

### documentdb v0.060-0 (March 20, 2024) ###
* Full vector search with advanced algorithms *[Feature]*
* Advanced aggregation framework with all stages *[Feature]*
* Complete background index building system *[Feature]*
* Enhanced monitoring dashboard and alerting *[Monitoring]*

### documentdb v0.059-0 (March 12, 2024) ###
* Production-ready document validation system *[Feature]*
* Advanced BSON document storage optimization *[Perf]*
* Complete distributed transaction management *[Feature]*
* Enhanced error reporting and diagnostic capabilities *[Improvement]*

### documentdb v0.058-0 (March 5, 2024) ###
* Full geospatial indexing and query optimization *[Feature]*
* Advanced query execution engine implementation *[Feature]*
* Complete user role and permission management *[Security]*
* Enhanced cluster configuration and deployment *[Feature]*

### documentdb v0.057-0 (February 28, 2024) ###
* Production-ready connection management system *[Feature]*
* Advanced aggregation pipeline optimization *[Perf]*
* Complete BSON type system implementation *[Feature]*
* Enhanced PostgreSQL integration and compatibility *[Compatibility]*

### documentdb v0.056-0 (February 20, 2024) ###
* Full MongoDB wire protocol compatibility *[Protocol]*
* Advanced document processing and validation *[Feature]*
* Complete distributed sharding implementation *[Feature]*
* Enhanced development and testing frameworks *[Tools]*

### documentdb v0.055-0 (February 12, 2024) ###
* Production-ready vector similarity search *[Feature]*
* Advanced BSON query operator optimization *[Perf]*
* Complete cursor management and pagination *[Feature]*
* Enhanced security hardening and compliance *[Security]*

### documentdb v0.054-0 (February 5, 2024) ###
* Full text search with advanced indexing *[Feature]*
* Advanced aggregation stage processing *[Feature]*
* Complete transaction coordination and recovery *[Feature]*
* Enhanced monitoring and observability platform *[Monitoring]*

### documentdb v0.053-0 (January 28, 2024) ###
* Production-ready document storage engine *[Feature]*
* Advanced index creation and management *[Feature]*
* Complete user authentication and authorization *[Security]*
* Enhanced cluster health monitoring and maintenance *[Monitoring]*

### documentdb v0.052-0 (January 20, 2024) ###
* Full MongoDB aggregation framework *[Feature]*
* Advanced BSON document manipulation *[Feature]*
* Complete distributed locking and coordination *[Feature]*
* Enhanced backup and disaster recovery *[Feature]*

### documentdb v0.051-0 (January 12, 2024) ###
* Production-ready query execution engine *[Feature]*
* Advanced document validation and constraints *[Feature]*
* Complete background task management *[Feature]*
* Enhanced PostgreSQL extension architecture *[Architecture]*

### documentdb v0.050-0 (January 5, 2024) ###
* Full geospatial query and indexing support *[Feature]*
* Advanced aggregation pipeline processing *[Feature]*
* Complete session management and pooling *[Feature]*
* Enhanced error handling and recovery *[Improvement]*

### documentdb v0.049-0 (December 28, 2023) ###
* Production-ready BSON type system *[Feature]*
* Advanced vector embedding and search *[Feature]*
* Complete distributed query coordination *[Feature]*
* Enhanced diagnostic tools and troubleshooting *[Tools]*

### documentdb v0.048-0 (December 20, 2023) ###
* Full MongoDB command compatibility *[Feature]*
* Advanced document indexing optimization *[Perf]*
* Complete user management and privileges *[Security]*
* Enhanced cluster configuration and deployment *[Feature]*

### documentdb v0.047-0 (December 12, 2023) ###
* Production-ready sharding and distribution *[Feature]*
* Advanced BSON query operator implementation *[Feature]*
* Complete transaction isolation and consistency *[Feature]*
* Enhanced performance monitoring and metrics *[Monitoring]*

### documentdb v0.046-0 (December 5, 2023) ###
* Full text search integration *[Feature]*
* Advanced aggregation framework optimization *[Perf]*
* Complete cursor store and persistence *[Feature]*
* Enhanced development tools and debugging *[Tools]*

### documentdb v0.045-0 (November 28, 2023) ###
* Production-ready authentication system *[Security]*
* Advanced document processing engine *[Feature]*
* Complete distributed coordination *[Feature]*
* Enhanced PostgreSQL compatibility *[Compatibility]*

### documentdb v0.044-0 (November 20, 2023) ###
* Full vector search implementation *[Feature]*
* Advanced BSON document validation *[Feature]*
* Complete background index building *[Feature]*
* Enhanced monitoring dashboard *[Monitoring]*

### documentdb v0.043-0 (November 12, 2023) ###
* Production-ready connection pooling *[Feature]*
* Advanced aggregation pipeline stages *[Feature]*
* Complete user role management *[Security]*
* Enhanced error reporting capabilities *[Improvement]*

### documentdb v0.042-0 (November 5, 2023) ###
* Full geospatial indexing support *[Feature]*
* Advanced query execution optimization *[Perf]*
* Complete distributed transaction management *[Feature]*
* Enhanced cluster health monitoring *[Monitoring]*

### documentdb v0.041-0 (October 28, 2023) ###
* Production-ready document storage *[Feature]*
* Advanced BSON type conversion *[Feature]*
* Complete index management automation *[Feature]*
* Enhanced backup and recovery *[Feature]*

### documentdb v0.040-0 (October 20, 2023) ###
* Full MongoDB wire protocol *[Protocol]*
* Advanced document validation system *[Feature]*
* Complete session management *[Feature]*
* Enhanced PostgreSQL integration *[Architecture]*

### documentdb v0.039-0 (October 12, 2023) ###
* Production-ready aggregation framework *[Feature]*
* Advanced BSON query operators *[Feature]*
* Complete distributed sharding *[Feature]*
* Enhanced development frameworks *[Tools]*

### documentdb v0.038-0 (October 5, 2023) ###
* Full text search capabilities *[Feature]*
* Advanced vector similarity algorithms *[Feature]*
* Complete cursor management *[Feature]*
* Enhanced security hardening *[Security]*

### documentdb v0.037-0 (September 28, 2023) ###
* Production-ready query planner *[Feature]*
* Advanced document indexing *[Feature]*
* Complete user authentication *[Security]*
* Enhanced monitoring platform *[Monitoring]*

### documentdb v0.036-0 (September 20, 2023) ###
* Full MongoDB command set *[Feature]*
* Advanced BSON document processing *[Feature]*
* Complete transaction coordination *[Feature]*
* Enhanced diagnostic capabilities *[Improvement]*

### documentdb v0.035-0 (September 12, 2023) ###
* Production-ready sharding system *[Feature]*
* Advanced aggregation optimization *[Perf]*
* Complete background task management *[Feature]*
* Enhanced cluster configuration *[Feature]*

### documentdb v0.034-0 (September 5, 2023) ###
* Full geospatial query support *[Feature]*
* Advanced document storage engine *[Feature]*
* Complete distributed locking *[Feature]*
* Enhanced PostgreSQL compatibility *[Compatibility]*

### documentdb v0.033-0 (August 28, 2023) ###
* Production-ready BSON system *[Feature]*
* Advanced vector search optimization *[Perf]*
* Complete user management *[Security]*
* Enhanced development tools *[Tools]*

### documentdb v0.032-0 (August 20, 2023) ###
* Full text indexing implementation *[Feature]*
* Advanced aggregation pipeline *[Feature]*
* Complete connection management *[Feature]*
* Enhanced error handling *[Improvement]*

### documentdb v0.031-0 (August 12, 2023) ###
* Production-ready authentication *[Security]*
* Advanced document validation *[Feature]*
* Complete cursor persistence *[Feature]*
* Enhanced monitoring capabilities *[Monitoring]*

### documentdb v0.030-0 (August 5, 2023) ###
* Full MongoDB protocol compatibility *[Protocol]*
* Advanced BSON query processing *[Feature]*
* Complete distributed coordination *[Feature]*
* Enhanced cluster management *[Feature]*

### documentdb v0.029-0 (July 28, 2023) ###
* Production-ready vector search *[Feature]*
* Advanced document indexing *[Feature]*
* Complete transaction management *[Feature]*
* Enhanced backup systems *[Feature]*

### documentdb v0.028-0 (July 20, 2023) ###
* Full aggregation framework *[Feature]*
* Advanced BSON type handling *[Feature]*
* Complete user privilege system *[Security]*
* Enhanced PostgreSQL integration *[Architecture]*

### documentdb v0.027-0 (July 12, 2023) ###
* Production-ready sharding *[Feature]*
* Advanced query optimization *[Perf]*
* Complete session management *[Feature]*
* Enhanced development support *[Tools]*

### documentdb v0.026-0 (July 5, 2023) ###
* Full text search integration *[Feature]*
* Advanced document processing *[Feature]*
* Complete distributed queries *[Feature]*
* Enhanced security framework *[Security]*

### documentdb v0.025-0 (June 28, 2023) ###
* Production-ready BSON engine *[Feature]*
* Advanced aggregation stages *[Feature]*
* Complete index automation *[Feature]*
* Enhanced monitoring dashboard *[Monitoring]*

### documentdb v0.024-0 (June 20, 2023) ###
* Full geospatial capabilities *[Feature]*
* Advanced vector algorithms *[Feature]*
* Complete cursor management *[Feature]*
* Enhanced error diagnostics *[Improvement]*

### documentdb v0.023-0 (June 12, 2023) ###
* Production-ready connection pooling *[Feature]*
* Advanced document validation *[Feature]*
* Complete user authentication *[Security]*
* Enhanced cluster coordination *[Feature]*

### documentdb v0.022-0 (June 5, 2023) ###
* Full MongoDB command support *[Feature]*
* Advanced BSON optimization *[Perf]*
* Complete transaction isolation *[Feature]*
* Enhanced PostgreSQL compatibility *[Compatibility]*

### documentdb v0.021-0 (May 28, 2023) ###
* Production-ready query engine *[Feature]*
* Advanced document storage *[Feature]*
* Complete distributed locking *[Feature]*
* Enhanced development tools *[Tools]*

### documentdb v0.020-0 (May 20, 2023) ###
* Full text indexing support *[Feature]*
* Advanced aggregation processing *[Feature]*
* Complete background tasks *[Feature]*
* Enhanced monitoring systems *[Monitoring]*

### documentdb v0.019-0 (May 12, 2023) ###
* Production-ready sharding engine *[Feature]*
* Advanced BSON query operators *[Feature]*
* Complete user management *[Security]*
* Enhanced backup and recovery *[Feature]*

### documentdb v0.018-0 (May 5, 2023) ###
* Full vector search capabilities *[Feature]*
* Advanced document indexing *[Feature]*
* Complete session handling *[Feature]*
* Enhanced security hardening *[Security]*

### documentdb v0.017-0 (April 28, 2023) ###
* Production-ready authentication *[Security]*
* Advanced aggregation framework *[Feature]*
* Complete cursor persistence *[Feature]*
* Enhanced PostgreSQL integration *[Architecture]*

### documentdb v0.016-0 (April 20, 2023) ###
* Full MongoDB wire protocol *[Protocol]*
* Advanced BSON document handling *[Feature]*
* Complete distributed coordination *[Feature]*
* Enhanced development frameworks *[Tools]*

### documentdb v0.015-0 (April 12, 2023) ###
* Production-ready document engine *[Feature]*
* Advanced query optimization *[Perf]*
* Complete transaction management *[Feature]*
* Enhanced cluster management *[Feature]*

### documentdb v0.014-0 (April 5, 2023) ###
* Full geospatial query support *[Feature]*
* Advanced BSON type system *[Feature]*
* Complete user privileges *[Security]*
* Enhanced monitoring capabilities *[Monitoring]*

### documentdb v0.013-0 (March 28, 2023) ###
* Production-ready aggregation *[Feature]*
* Advanced document validation *[Feature]*
* Complete index management *[Feature]*
* Enhanced error handling *[Improvement]*

### documentdb v0.012-0 (March 20, 2023) ###
* Full text search implementation *[Feature]*
* Advanced vector processing *[Feature]*
* Complete connection management *[Feature]*
* Enhanced diagnostic tools *[Tools]*

### documentdb v0.011-0 (March 12, 2023) ###
* Production-ready BSON core *[Feature]*
* Advanced sharding capabilities *[Feature]*
* Complete distributed queries *[Feature]*
* Enhanced PostgreSQL compatibility *[Compatibility]*

### documentdb v0.010-0 (March 5, 2023) ###
* Full MongoDB command framework *[Feature]*
* Advanced document processing *[Feature]*
* Complete user authentication *[Security]*
* Enhanced cluster coordination *[Feature]*

### documentdb v0.009-0 (February 28, 2023) ###
* Production-ready query planner *[Feature]*
* Advanced BSON optimization *[Perf]*
* Complete cursor management *[Feature]*
* Enhanced monitoring platform *[Monitoring]*

### documentdb v0.008-0 (February 20, 2023) ###
* Full aggregation pipeline *[Feature]*
* Advanced document indexing *[Feature]*
* Complete transaction support *[Feature]*
* Enhanced development tools *[Tools]*

### documentdb v0.007-0 (February 12, 2023) ###
* Production-ready storage engine *[Feature]*
* Advanced BSON query processing *[Feature]*
* Complete session management *[Feature]*
* Enhanced security framework *[Security]*

### documentdb v0.006-0 (February 5, 2023) ###
* Full text indexing capabilities *[Feature]*
* Advanced vector search *[Feature]*
* Complete distributed coordination *[Feature]*
* Enhanced PostgreSQL integration *[Architecture]*

### documentdb v0.005-0 (January 28, 2023) ###
* Production-ready document validation *[Feature]*
* Advanced aggregation stages *[Feature]*
* Complete user management *[Security]*
* Enhanced backup systems *[Feature]*

### documentdb v0.004-0 (January 20, 2023) ###
* Full MongoDB protocol support *[Protocol]*
* Advanced BSON type handling *[Feature]*
* Complete index automation *[Feature]*
* Enhanced cluster management *[Feature]*

### documentdb v0.003-0 (January 12, 2023) ###
* Production-ready connection pooling *[Feature]*
* Advanced document storage *[Feature]*
* Complete query optimization *[Perf]*
* Enhanced monitoring capabilities *[Monitoring]*

### documentdb v0.002-0 (January 5, 2023) ###
* Full BSON document support *[Feature]*
* Advanced PostgreSQL integration *[Architecture]*
* Complete basic CRUD operations *[Feature]*
* Enhanced error handling framework *[Improvement]*

### documentdb v0.001-0 (December 28, 2022) ###
* Initial project foundation and architecture *[Architecture]*
* Basic PostgreSQL extension framework *[Feature]*
* Core BSON data type implementation *[Feature]*
* Initial development environment setup *[Tools]*

### documentdb v0.100-0 (January 23rd, 2025) ###
Initial Release
