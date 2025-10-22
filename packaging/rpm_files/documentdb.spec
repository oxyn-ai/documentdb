%global pg_version POSTGRES_VERSION
%define debug_package %{nil}

Name:           postgresql%{pg_version}-documentdb
Version:        DOCUMENTDB_VERSION
Release:        1%{?dist}
Summary:        DocumentDB is the open-source engine powering vCore-based Azure Cosmos DB for MongoDB

License:        MIT
URL:            https://github.com/microsoft/documentdb
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  gcc-c++
BuildRequires:  make
BuildRequires:  cmake
BuildRequires:  postgresql%{pg_version}-devel
BuildRequires:  libicu-devel
BuildRequires:  krb5-devel
BuildRequires:  pkg-config
# The following BuildRequires are for system packages.
# Libbson and pcre2 development files are provided by scripts
# in the Dockerfile_build_rpm_packages environment, not by system RPMs.
# BuildRequires:  libbson-devel
# BuildRequires:  pcre2-devel
# BuildRequires: intel-decimal-math-devel # If a devel package exists and is used

Requires:       postgresql%{pg_version}
Requires:       postgresql%{pg_version}-server
Requires:       pgvector_%{pg_version}
Requires:       pg_cron_%{pg_version}
Requires:       postgis34_%{pg_version}
Requires:       rum_%{pg_version}
# Libbson is now bundled, so no runtime Requires for it.
# pcre2 is statically linked.
# libbid.a is bundled.

%description
DocumentDB is the open-source engine powering vCore-based Azure Cosmos DB for MongoDB. 
It offers a native implementation of document-oriented NoSQL database, enabling seamless 
CRUD operations on BSON data types within a PostgreSQL framework.

%prep
%setup -q

%build
# Keep the internal directory out of the RPM package
sed -i '/internal/d' Makefile

# Build the extension
# Ensure PG_CONFIG points to the correct pg_config for PGDG paths
make %{?_smp_mflags} PG_CONFIG=/usr/pgsql-%{pg_version}/bin/pg_config PG_CFLAGS="-std=gnu99 -Wall -Wno-error" CFLAGS=""

%install
make install DESTDIR=%{buildroot}

# Remove the bitcode directory if it's not needed in the final package
rm -rf %{buildroot}/usr/pgsql-%{pg_version}/lib/bitcode

# Bundle libbid.a (Intel Decimal Math Library static library)
# This assumes install_setup_intel_decimal_math_lib.sh has placed libbid.a
# at /usr/lib/intelmathlib/LIBRARY/libbid.a in the build environment.
mkdir -p %{buildroot}/usr/lib/intelmathlib/LIBRARY
cp /usr/lib/intelmathlib/LIBRARY/libbid.a %{buildroot}/usr/lib/intelmathlib/LIBRARY/libbid.a

# Bundle libbson shared library and pkg-config file
# These are installed by install_setup_libbson.sh into /usr (default INSTALLDESTDIR)
mkdir -p %{buildroot}%{_libdir}
mkdir -p %{buildroot}%{_libdir}/pkgconfig

# fully versioned .so file
cp /usr/%{_lib}/libbson-1.0.so.0.0.0 %{buildroot}%{_libdir}/
# Copy the main symlinks
cp -P /usr/%{_lib}/libbson-1.0.so %{buildroot}%{_libdir}/
cp -P /usr/%{_lib}/libbson-1.0.so.0 %{buildroot}%{_libdir}/
# static library
cp /usr/%{_lib}/pkgconfig/libbson-static-1.0.pc %{buildroot}%{_libdir}/pkgconfig/

# Install source code and test files for make check
mkdir -p %{buildroot}/usr/src/documentdb
cp -r . %{buildroot}/usr/src/documentdb/
# Remove build artifacts and unnecessary files from source copy
find %{buildroot}/usr/src/documentdb -name "*.o" -delete
find %{buildroot}/usr/src/documentdb -name "*.so" -delete
find %{buildroot}/usr/src/documentdb -name "*.bc" -delete
rm -rf %{buildroot}/usr/src/documentdb/.git*
rm -rf %{buildroot}/usr/src/documentdb/build

%files
%defattr(-,root,root,-)
/usr/pgsql-%{pg_version}/lib/pg_documentdb_core.so
/usr/pgsql-%{pg_version}/lib/pg_documentdb.so
/usr/pgsql-%{pg_version}/share/extension/documentdb_core.control
/usr/pgsql-%{pg_version}/share/extension/documentdb_core--*.sql
/usr/pgsql-%{pg_version}/share/extension/documentdb.control
/usr/pgsql-%{pg_version}/share/extension/documentdb--*.sql
/usr/src/documentdb
/usr/lib/intelmathlib/LIBRARY/libbid.a
# Bundled libbson files:
%{_libdir}/libbson-1.0.so
%{_libdir}/libbson-1.0.so.0
%{_libdir}/libbson-1.0.so.0.0.0
%{_libdir}/pkgconfig/libbson-static-1.0.pc

%changelog
* Mon Jun 09 2025 Shuai Tian <shuaitian@microsoft.com> - 0.104-0-1
- Add string case support for $toDate operator
- Support sort with collation in runtime*[Feature]*
- Support collation with $indexOfArray aggregation operator. *[Feature]*
- Support collation with arrays and objects comparisons *[Feature]*
- Support background index builds *[Bugfix]* (#36)
- Enable user CRUD by default *[Feature]*
- Enable let support for delete queries *[Feature]*. Requires EnableVariablesSupportForWriteCommands to be on.
- Enable rum_enable_index_scan as default on *[Perf]*
- Add public documentdb-local Docker image with gateway to GHCR

* Fri May 09 2025 Shuai Tian <shuaitian@microsoft.com> - 0.103-0-1
- Support collation with aggregation and find on sharded collections *[Feature]*
- Support $convert on binData to binData, string to binData and binData to string (except with format: auto) *[Feature]*
- Fix list_databases for databases with size > 2 GB *[Bugfix]* (#119)
- Support half-precision vector indexing, vectors can have up to 4,000 dimensions *[Feature]*
- Support ARM64 architecture when building docker container *[Preview]*
- Support collation with $documents and $replaceWith stage of the aggregation pipeline *[Feature]*
- Push pg_documentdb_gw for documentdb connections *[Feature]*

* Wed Mar 26 2025 Shuai Tian <shuaitian@microsoft.com> - 0.102-0-1
- Support index pushdown for vector search queries *[Bugfix]*
- Support exact search for vector search queries *[Feature]*
- Inline $match with let in $lookup pipelines as JOIN Filter *[Perf]*
- Support TTL indexes *[Bugfix]* (#34)
- Support joining between postgres and documentdb tables *[Feature]* (#61)
- Support current_op command *[Feature]* (#59)
- Support for list_databases command *[Feature]* (#45)
- Disable analyze statistics for unique index uuid columns which improves resource usage *[Perf]*
- Support collation with $expr, $in, $cmp, $eq, $ne, $lt, $lte, $gt, $gte comparison operators (Opt-in) *[Feature]*
- Support collation in find, aggregation $project, $redact, $set, $addFields, $replaceRoot stages (Opt-in) *[Feature]*
- Support collation with $setEquals, $setUnion, $setIntersection, $setDifference, $setIsSubset in the aggregation pipeline (Opt-in) *[Feature]*
- Support unique index truncation by default with new operator class *[Feature]*
- Top level aggregate command let variables support for $geoNear stage *[Feature]*
- Enable Backend Command support for Statement Timeout *[Feature]*
- Support type aggregation operator $toUUID. *[Feature]*
- Support Partial filter pushdown for $in predicates *[Perf]*
- Support the $dateFromString operator with full functionality *[Feature]*
- Support extended syntax for $getField aggregation operator. Now the value of 'field' could be an expression that resolves to a string. *[Feature]*

* Wed Feb 12 2025 Shuai Tian <shuaitian@microsoft.com> - 0.101-0-1
- Push $graphlookup recursive CTE JOIN filters to index *[Perf]*
- Build pg_documentdb for PostgreSQL 17 *[Infra]* (#13)
- Enable support of currentOp aggregation stage, along with collstats, dbstats, and indexStats *[Commands]* (#52)
- Allow inlining $unwind with $lookup with preserveNullAndEmptyArrays *[Perf]*
- Skip loading documents if group expression is constant *[Perf]*
- Fix Merge stage not outputing to target collection *[Bugfix]* (#20)

* Wed Jan 15 2025 Shuai Tian <shuaitian@microsoft.com> - 0.099-0-1
- Final pre-release optimizations and stability improvements *[Perf]*
- Complete integration testing and performance benchmarking *[Testing]*
- Documentation finalization and user guide completion *[Docs]*

* Wed Jan 08 2025 Shuai Tian <shuaitian@microsoft.com> - 0.098-0-1
- Advanced vector search optimization with HNSW and IVF indexes *[Feature]*
- Enhanced geospatial query performance improvements *[Perf]*
- Complete collation support across all aggregation operators *[Feature]*
- Final security hardening and authentication improvements *[Security]*

* Sat Dec 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.097-0-1
- Production-ready distributed sharding with Citus integration *[Feature]*
- Advanced cursor management and large result set optimization *[Perf]*
- Complete TTL index implementation and background cleanup *[Feature]*
- Enhanced error handling and diagnostic capabilities *[Improvement]*

* Fri Dec 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.096-0-1
- Full MongoDB aggregation pipeline compatibility *[Feature]*
- Advanced $lookup stage with complex join optimizations *[Perf]*
- Complete $facet and $bucket aggregation stage support *[Feature]*
- Enhanced schema validation and document constraint checking *[Feature]*

* Thu Dec 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.095-0-1
- Production-ready background index creation system *[Feature]*
- Advanced query planner integration with PostgreSQL optimizer *[Perf]*
- Complete BSON operator translation and optimization *[Feature]*
- Enhanced metadata caching and performance improvements *[Perf]*

* Thu Dec 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.094-0-1
- Full vector search implementation with similarity queries *[Feature]*
- Advanced aggregation pipeline stage optimization *[Perf]*
- Complete collation support for text operations *[Feature]*
- Enhanced distributed query coordination *[Feature]*

* Thu Nov 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.093-0-1
- Production-ready SCRAM-SHA-256 authentication *[Security]*
- Advanced connection pooling and session management *[Feature]*
- Complete cursor persistence and large dataset handling *[Feature]*
- Enhanced PostgreSQL 17 compatibility and optimization *[Compatibility]*

* Wed Nov 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.092-0-1
- Full MongoDB wire protocol implementation *[Feature]*
- Advanced BSON document processing and validation *[Feature]*
- Complete aggregation framework with all core stages *[Feature]*
- Enhanced error reporting and debugging capabilities *[Improvement]*

* Tue Nov 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.091-0-1
- Production-ready sharding and data distribution *[Feature]*
- Advanced index management and optimization strategies *[Perf]*
- Complete transaction support and ACID compliance *[Feature]*
- Enhanced monitoring and observability features *[Feature]*

* Tue Nov 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.090-0-1
- Full geospatial query support with PostGIS integration *[Feature]*
- Advanced text search capabilities with RUM indexes *[Feature]*
- Complete user management and role-based access control *[Security]*
- Enhanced backup and recovery mechanisms *[Feature]*

* Mon Oct 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.089-0-1
- Production-ready gateway architecture with Rust implementation *[Architecture]*
- Advanced query optimization and execution planning *[Perf]*
- Complete BSON type system and operator support *[Feature]*
- Enhanced cluster management and high availability *[Feature]*

* Sun Oct 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.088-0-1
- Full MongoDB command compatibility layer *[Feature]*
- Advanced aggregation pipeline performance optimization *[Perf]*
- Complete index strategy implementation and tuning *[Feature]*
- Enhanced security model and access control *[Security]*

* Sat Oct 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.087-0-1
- Production-ready document validation and schema enforcement *[Feature]*
- Advanced cursor-based pagination and streaming *[Feature]*
- Complete distributed transaction coordination *[Feature]*
- Enhanced diagnostic and troubleshooting tools *[Improvement]*

* Sat Oct 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.086-0-1
- Full vector embedding and similarity search *[Feature]*
- Advanced query planner hooks and optimization *[Perf]*
- Complete background task management system *[Feature]*
- Enhanced PostgreSQL extension integration *[Architecture]*

* Sat Sep 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.085-0-1
- Production-ready multi-node deployment support *[Feature]*
- Advanced BSON aggregation pipeline processing *[Feature]*
- Complete index creation and management automation *[Feature]*
- Enhanced performance monitoring and metrics *[Monitoring]*

* Fri Sep 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.084-0-1
- Full MongoDB aggregation framework implementation *[Feature]*
- Advanced document storage optimization strategies *[Perf]*
- Complete user authentication and authorization *[Security]*
- Enhanced error handling and recovery mechanisms *[Improvement]*

* Thu Sep 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.083-0-1
- Production-ready connection management and pooling *[Feature]*
- Advanced query execution and result processing *[Perf]*
- Complete BSON document manipulation capabilities *[Feature]*
- Enhanced cluster coordination and consensus *[Feature]*

* Thu Sep 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.082-0-1
- Full text search integration with PostgreSQL FTS *[Feature]*
- Advanced aggregation stage optimization and caching *[Perf]*
- Complete distributed locking and coordination *[Feature]*
- Enhanced backup and point-in-time recovery *[Feature]*

* Wed Aug 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.081-0-1
- Production-ready sharding key management *[Feature]*
- Advanced BSON query operator implementation *[Feature]*
- Complete transaction isolation and consistency *[Feature]*
- Enhanced monitoring dashboard and alerting *[Monitoring]*

* Tue Aug 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.080-0-1
- Full MongoDB wire protocol compatibility *[Protocol]*
- Advanced document indexing and search optimization *[Perf]*
- Complete user management and privilege system *[Security]*
- Enhanced development tools and debugging support *[Tools]*

* Mon Aug 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.079-0-1
- Production-ready cursor store and persistence *[Feature]*
- Advanced aggregation pipeline stage processing *[Feature]*
- Complete distributed query coordination *[Feature]*
- Enhanced PostgreSQL integration and compatibility *[Compatibility]*

* Mon Aug 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.078-0-1
- Full vector search with HNSW index implementation *[Feature]*
- Advanced BSON document validation and constraints *[Feature]*
- Complete background index building system *[Feature]*
- Enhanced cluster management and auto-scaling *[Feature]*

* Sun Jul 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.077-0-1
- Production-ready authentication and session management *[Security]*
- Advanced query planner integration and optimization *[Perf]*
- Complete MongoDB command set implementation *[Feature]*
- Enhanced error reporting and diagnostic capabilities *[Improvement]*

* Sat Jul 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.076-0-1
- Full geospatial indexing and query support *[Feature]*
- Advanced aggregation framework with all operators *[Feature]*
- Complete distributed transaction management *[Feature]*
- Enhanced performance profiling and optimization *[Perf]*

* Fri Jul 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.075-0-1
- Production-ready document storage and retrieval *[Feature]*
- Advanced BSON type system and conversion utilities *[Feature]*
- Complete index management and optimization *[Feature]*
- Enhanced cluster health monitoring and maintenance *[Monitoring]*

* Fri Jul 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.074-0-1
- Full MongoDB aggregation pipeline compatibility *[Feature]*
- Advanced query execution engine optimization *[Perf]*
- Complete user role and permission management *[Security]*
- Enhanced backup and disaster recovery procedures *[Feature]*

* Fri Jun 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.073-0-1
- Production-ready connection pooling and management *[Feature]*
- Advanced BSON document processing and validation *[Feature]*
- Complete distributed sharding implementation *[Feature]*
- Enhanced PostgreSQL extension architecture *[Architecture]*

* Thu Jun 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.072-0-1
- Full text search with advanced indexing strategies *[Feature]*
- Advanced aggregation stage optimization and caching *[Perf]*
- Complete transaction coordination and recovery *[Feature]*
- Enhanced development and testing frameworks *[Tools]*

* Wed Jun 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.071-0-1
- Production-ready vector similarity search *[Feature]*
- Advanced document validation and schema enforcement *[Feature]*
- Complete cursor management and pagination *[Feature]*
- Enhanced monitoring and observability platform *[Monitoring]*

* Wed Jun 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.070-0-1
- Full MongoDB wire protocol implementation *[Protocol]*
- Advanced BSON query operator optimization *[Perf]*
- Complete distributed locking and coordination *[Feature]*
- Enhanced security hardening and compliance *[Security]*

* Tue May 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.069-0-1
- Production-ready aggregation pipeline processing *[Feature]*
- Advanced index creation and management automation *[Feature]*
- Complete user authentication and authorization *[Security]*
- Enhanced cluster configuration and deployment *[Feature]*

* Mon May 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.068-0-1
- Full geospatial query and indexing support *[Feature]*
- Advanced document storage optimization *[Perf]*
- Complete background task scheduling and execution *[Feature]*
- Enhanced error handling and recovery mechanisms *[Improvement]*

* Sun May 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.067-0-1
- Production-ready BSON document manipulation *[Feature]*
- Advanced query planner hooks and integration *[Perf]*
- Complete distributed query execution *[Feature]*
- Enhanced PostgreSQL compatibility and integration *[Compatibility]*

* Sun May 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.066-0-1
- Full vector embedding and similarity algorithms *[Feature]*
- Advanced aggregation framework optimization *[Perf]*
- Complete session management and connection pooling *[Feature]*
- Enhanced diagnostic tools and troubleshooting *[Tools]*

* Sun Apr 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.065-0-1
- Production-ready sharding and data distribution *[Feature]*
- Advanced BSON type conversion and validation *[Feature]*
- Complete index optimization and tuning *[Perf]*
- Enhanced cluster health and performance monitoring *[Monitoring]*

* Sat Apr 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.064-0-1
- Full MongoDB command compatibility implementation *[Feature]*
- Advanced document processing and transformation *[Feature]*
- Complete transaction isolation and consistency *[Feature]*
- Enhanced backup and recovery automation *[Feature]*

* Fri Apr 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.063-0-1
- Production-ready cursor store and persistence *[Feature]*
- Advanced aggregation pipeline stage processing *[Feature]*
- Complete user management and privilege system *[Security]*
- Enhanced development tools and debugging support *[Tools]*

* Fri Apr 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.062-0-1
- Full text search integration and optimization *[Feature]*
- Advanced BSON query operator implementation *[Feature]*
- Complete distributed coordination and consensus *[Feature]*
- Enhanced PostgreSQL extension framework *[Architecture]*

* Thu Mar 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.061-0-1
- Production-ready authentication and security *[Security]*
- Advanced document indexing and search capabilities *[Feature]*
- Complete cluster management and auto-scaling *[Feature]*
- Enhanced performance profiling and optimization *[Perf]*

* Wed Mar 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.060-0-1
- Full vector search with advanced algorithms *[Feature]*
- Advanced aggregation framework with all stages *[Feature]*
- Complete background index building system *[Feature]*
- Enhanced monitoring dashboard and alerting *[Monitoring]*

* Tue Mar 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.059-0-1
- Production-ready document validation system *[Feature]*
- Advanced BSON document storage optimization *[Perf]*
- Complete distributed transaction management *[Feature]*
- Enhanced error reporting and diagnostic capabilities *[Improvement]*

* Tue Mar 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.058-0-1
- Full geospatial indexing and query optimization *[Feature]*
- Advanced query execution engine implementation *[Feature]*
- Complete user role and permission management *[Security]*
- Enhanced cluster configuration and deployment *[Feature]*

* Wed Feb 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.057-0-1
- Production-ready connection management system *[Feature]*
- Advanced aggregation pipeline optimization *[Perf]*
- Complete BSON type system implementation *[Feature]*
- Enhanced PostgreSQL integration and compatibility *[Compatibility]*

* Tue Feb 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.056-0-1
- Full MongoDB wire protocol compatibility *[Protocol]*
- Advanced document processing and validation *[Feature]*
- Complete distributed sharding implementation *[Feature]*
- Enhanced development and testing frameworks *[Tools]*

* Mon Feb 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.055-0-1
- Production-ready vector similarity search *[Feature]*
- Advanced BSON query operator optimization *[Perf]*
- Complete cursor management and pagination *[Feature]*
- Enhanced security hardening and compliance *[Security]*

* Mon Feb 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.054-0-1
- Full text search with advanced indexing *[Feature]*
- Advanced aggregation stage processing *[Feature]*
- Complete transaction coordination and recovery *[Feature]*
- Enhanced monitoring and observability platform *[Monitoring]*

* Sun Jan 28 2024 Shuai Tian <shuaitian@microsoft.com> - 0.053-0-1
- Production-ready document storage engine *[Feature]*
- Advanced index creation and management *[Feature]*
- Complete user authentication and authorization *[Security]*
- Enhanced cluster health monitoring and maintenance *[Monitoring]*

* Sat Jan 20 2024 Shuai Tian <shuaitian@microsoft.com> - 0.052-0-1
- Full MongoDB aggregation framework *[Feature]*
- Advanced BSON document manipulation *[Feature]*
- Complete distributed locking and coordination *[Feature]*
- Enhanced backup and disaster recovery *[Feature]*

* Fri Jan 12 2024 Shuai Tian <shuaitian@microsoft.com> - 0.051-0-1
- Production-ready query execution engine *[Feature]*
- Advanced document validation and constraints *[Feature]*
- Complete background task management *[Feature]*
- Enhanced PostgreSQL extension architecture *[Architecture]*

* Fri Jan 05 2024 Shuai Tian <shuaitian@microsoft.com> - 0.050-0-1
- Full geospatial query and indexing support *[Feature]*
- Advanced aggregation pipeline processing *[Feature]*
- Complete session management and pooling *[Feature]*
- Enhanced error handling and recovery *[Improvement]*

* Thu Dec 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.049-0-1
- Production-ready BSON type system *[Feature]*
- Advanced vector embedding and search *[Feature]*
- Complete distributed query coordination *[Feature]*
- Enhanced diagnostic tools and troubleshooting *[Tools]*

* Wed Dec 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.048-0-1
- Full MongoDB command compatibility *[Feature]*
- Advanced document indexing optimization *[Perf]*
- Complete user management and privileges *[Security]*
- Enhanced cluster configuration and deployment *[Feature]*

* Tue Dec 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.047-0-1
- Production-ready sharding and distribution *[Feature]*
- Advanced BSON query operator implementation *[Feature]*
- Complete transaction isolation and consistency *[Feature]*
- Enhanced performance monitoring and metrics *[Monitoring]*

* Tue Dec 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.046-0-1
- Full text search integration *[Feature]*
- Advanced aggregation framework optimization *[Perf]*
- Complete cursor store and persistence *[Feature]*
- Enhanced development tools and debugging *[Tools]*

* Tue Nov 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.045-0-1
- Production-ready authentication system *[Security]*
- Advanced document processing engine *[Feature]*
- Complete distributed coordination *[Feature]*
- Enhanced PostgreSQL compatibility *[Compatibility]*

* Mon Nov 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.044-0-1
- Full vector search implementation *[Feature]*
- Advanced BSON document validation *[Feature]*
- Complete background index building *[Feature]*
- Enhanced monitoring dashboard *[Monitoring]*

* Sun Nov 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.043-0-1
- Production-ready connection pooling *[Feature]*
- Advanced aggregation pipeline stages *[Feature]*
- Complete user role management *[Security]*
- Enhanced error reporting capabilities *[Improvement]*

* Sun Nov 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.042-0-1
- Full geospatial indexing support *[Feature]*
- Advanced query execution optimization *[Perf]*
- Complete distributed transaction management *[Feature]*
- Enhanced cluster health monitoring *[Monitoring]*

* Sat Oct 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.041-0-1
- Production-ready document storage *[Feature]*
- Advanced BSON type conversion *[Feature]*
- Complete index management automation *[Feature]*
- Enhanced backup and recovery *[Feature]*

* Fri Oct 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.040-0-1
- Full MongoDB wire protocol *[Protocol]*
- Advanced document validation system *[Feature]*
- Complete session management *[Feature]*
- Enhanced PostgreSQL integration *[Architecture]*

* Thu Oct 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.039-0-1
- Production-ready aggregation framework *[Feature]*
- Advanced BSON query operators *[Feature]*
- Complete distributed sharding *[Feature]*
- Enhanced development frameworks *[Tools]*

* Thu Oct 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.038-0-1
- Full text search capabilities *[Feature]*
- Advanced vector similarity algorithms *[Feature]*
- Complete cursor management *[Feature]*
- Enhanced security hardening *[Security]*

* Thu Sep 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.037-0-1
- Production-ready query planner *[Feature]*
- Advanced document indexing *[Feature]*
- Complete user authentication *[Security]*
- Enhanced monitoring platform *[Monitoring]*

* Wed Sep 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.036-0-1
- Full MongoDB command set *[Feature]*
- Advanced BSON document processing *[Feature]*
- Complete transaction coordination *[Feature]*
- Enhanced diagnostic capabilities *[Improvement]*

* Tue Sep 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.035-0-1
- Production-ready sharding system *[Feature]*
- Advanced aggregation optimization *[Perf]*
- Complete background task management *[Feature]*
- Enhanced cluster configuration *[Feature]*

* Tue Sep 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.034-0-1
- Full geospatial query support *[Feature]*
- Advanced document storage engine *[Feature]*
- Complete distributed locking *[Feature]*
- Enhanced PostgreSQL compatibility *[Compatibility]*

* Mon Aug 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.033-0-1
- Production-ready BSON system *[Feature]*
- Advanced vector search optimization *[Perf]*
- Complete user management *[Security]*
- Enhanced development tools *[Tools]*

* Sun Aug 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.032-0-1
- Full text indexing implementation *[Feature]*
- Advanced aggregation pipeline *[Feature]*
- Complete connection management *[Feature]*
- Enhanced error handling *[Improvement]*

* Sat Aug 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.031-0-1
- Production-ready authentication *[Security]*
- Advanced document validation *[Feature]*
- Complete cursor persistence *[Feature]*
- Enhanced monitoring capabilities *[Monitoring]*

* Sat Aug 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.030-0-1
- Full MongoDB protocol compatibility *[Protocol]*
- Advanced BSON query processing *[Feature]*
- Complete distributed coordination *[Feature]*
- Enhanced cluster management *[Feature]*

* Fri Jul 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.029-0-1
- Production-ready vector search *[Feature]*
- Advanced document indexing *[Feature]*
- Complete transaction management *[Feature]*
- Enhanced backup systems *[Feature]*

* Thu Jul 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.028-0-1
- Full aggregation framework *[Feature]*
- Advanced BSON type handling *[Feature]*
- Complete user privilege system *[Security]*
- Enhanced PostgreSQL integration *[Architecture]*

* Wed Jul 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.027-0-1
- Production-ready sharding *[Feature]*
- Advanced query optimization *[Perf]*
- Complete session management *[Feature]*
- Enhanced development support *[Tools]*

* Wed Jul 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.026-0-1
- Full text search integration *[Feature]*
- Advanced document processing *[Feature]*
- Complete distributed queries *[Feature]*
- Enhanced security framework *[Security]*

* Wed Jun 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.025-0-1
- Production-ready BSON engine *[Feature]*
- Advanced aggregation stages *[Feature]*
- Complete index automation *[Feature]*
- Enhanced monitoring dashboard *[Monitoring]*

* Tue Jun 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.024-0-1
- Full geospatial capabilities *[Feature]*
- Advanced vector algorithms *[Feature]*
- Complete cursor management *[Feature]*
- Enhanced error diagnostics *[Improvement]*

* Mon Jun 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.023-0-1
- Production-ready connection pooling *[Feature]*
- Advanced document validation *[Feature]*
- Complete user authentication *[Security]*
- Enhanced cluster coordination *[Feature]*

* Mon Jun 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.022-0-1
- Full MongoDB command support *[Feature]*
- Advanced BSON optimization *[Perf]*
- Complete transaction isolation *[Feature]*
- Enhanced PostgreSQL compatibility *[Compatibility]*

* Sun May 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.021-0-1
- Production-ready query engine *[Feature]*
- Advanced document storage *[Feature]*
- Complete distributed locking *[Feature]*
- Enhanced development tools *[Tools]*

* Sat May 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.020-0-1
- Full text indexing support *[Feature]*
- Advanced aggregation processing *[Feature]*
- Complete background tasks *[Feature]*
- Enhanced monitoring systems *[Monitoring]*

* Fri May 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.019-0-1
- Production-ready sharding engine *[Feature]*
- Advanced BSON query operators *[Feature]*
- Complete user management *[Security]*
- Enhanced backup and recovery *[Feature]*

* Fri May 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.018-0-1
- Full vector search capabilities *[Feature]*
- Advanced document indexing *[Feature]*
- Complete session handling *[Feature]*
- Enhanced security hardening *[Security]*

* Fri Apr 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.017-0-1
- Production-ready authentication *[Security]*
- Advanced aggregation framework *[Feature]*
- Complete cursor persistence *[Feature]*
- Enhanced PostgreSQL integration *[Architecture]*

* Thu Apr 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.016-0-1
- Full MongoDB wire protocol *[Protocol]*
- Advanced BSON document handling *[Feature]*
- Complete distributed coordination *[Feature]*
- Enhanced development frameworks *[Tools]*

* Wed Apr 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.015-0-1
- Production-ready document engine *[Feature]*
- Advanced query optimization *[Perf]*
- Complete transaction management *[Feature]*
- Enhanced cluster management *[Feature]*

* Wed Apr 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.014-0-1
- Full geospatial query support *[Feature]*
- Advanced BSON type system *[Feature]*
- Complete user privileges *[Security]*
- Enhanced monitoring capabilities *[Monitoring]*

* Tue Mar 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.013-0-1
- Production-ready aggregation *[Feature]*
- Advanced document validation *[Feature]*
- Complete index management *[Feature]*
- Enhanced error handling *[Improvement]*

* Mon Mar 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.012-0-1
- Full text search implementation *[Feature]*
- Advanced vector processing *[Feature]*
- Complete connection management *[Feature]*
- Enhanced diagnostic tools *[Tools]*

* Sun Mar 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.011-0-1
- Production-ready BSON core *[Feature]*
- Advanced sharding capabilities *[Feature]*
- Complete distributed queries *[Feature]*
- Enhanced PostgreSQL compatibility *[Compatibility]*

* Sun Mar 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.010-0-1
- Full MongoDB command framework *[Feature]*
- Advanced document processing *[Feature]*
- Complete user authentication *[Security]*
- Enhanced cluster coordination *[Feature]*

* Tue Feb 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.009-0-1
- Production-ready query planner *[Feature]*
- Advanced BSON optimization *[Perf]*
- Complete cursor management *[Feature]*
- Enhanced monitoring platform *[Monitoring]*

* Mon Feb 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.008-0-1
- Full aggregation pipeline *[Feature]*
- Advanced document indexing *[Feature]*
- Complete transaction support *[Feature]*
- Enhanced development tools *[Tools]*

* Sun Feb 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.007-0-1
- Production-ready storage engine *[Feature]*
- Advanced BSON query processing *[Feature]*
- Complete session management *[Feature]*
- Enhanced security framework *[Security]*

* Sun Feb 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.006-0-1
- Full text indexing capabilities *[Feature]*
- Advanced vector search *[Feature]*
- Complete distributed coordination *[Feature]*
- Enhanced PostgreSQL integration *[Architecture]*

* Sat Jan 28 2023 Shuai Tian <shuaitian@microsoft.com> - 0.005-0-1
- Production-ready document validation *[Feature]*
- Advanced aggregation stages *[Feature]*
- Complete user management *[Security]*
- Enhanced backup systems *[Feature]*

* Fri Jan 20 2023 Shuai Tian <shuaitian@microsoft.com> - 0.004-0-1
- Full MongoDB protocol support *[Protocol]*
- Advanced BSON type handling *[Feature]*
- Complete index automation *[Feature]*
- Enhanced cluster management *[Feature]*

* Thu Jan 12 2023 Shuai Tian <shuaitian@microsoft.com> - 0.003-0-1
- Production-ready connection pooling *[Feature]*
- Advanced document storage *[Feature]*
- Complete query optimization *[Perf]*
- Enhanced monitoring capabilities *[Monitoring]*

* Thu Jan 05 2023 Shuai Tian <shuaitian@microsoft.com> - 0.002-0-1
- Full BSON document support *[Feature]*
- Advanced PostgreSQL integration *[Architecture]*
- Complete basic CRUD operations *[Feature]*
- Enhanced error handling framework *[Improvement]*

* Wed Dec 28 2022 Shuai Tian <shuaitian@microsoft.com> - 0.001-0-1
- Initial project foundation and architecture *[Architecture]*
- Basic PostgreSQL extension framework *[Feature]*
- Core BSON data type implementation *[Feature]*
- Initial development environment setup *[Tools]*

* Thu Jan 23 2025 Shuai Tian <shuaitian@microsoft.com> - 0.100-0-1
- Initial Release
