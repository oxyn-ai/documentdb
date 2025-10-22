# Introduction

`DocumentDB` is the engine powering vCore-based Azure Cosmos DB for MongoDB. It offers a native implementation of document-oriented NoSQL database, enabling seamless CRUD operations on BSON data types within a PostgreSQL framework. Beyond basic operations, DocumentDB empowers you to execute complex workloads, including full-text searches, geospatial queries, and vector embeddings on your dataset, delivering robust functionality and flexibility for diverse data management needs.

[PostgreSQL](https://www.postgresql.org/about/) is a powerful, open source object-relational database system that uses and extends the SQL language combined with many features that safely store and scale the most complicated data workloads.

## Components

The project comprises of two primary components, which work together to support document operations.

- **pg_documentdb_core :** PostgreSQL extension introducing BSON datatype support and operations for native Postgres.
- **pg_documentdb :** The public API surface for DocumentDB providing CRUD functionality on documents in the store.

## 未来发展规划 (Future Development Plans)

DocumentDB is continuously evolving to provide a more flexible and powerful hybrid database system that bridges the gap between traditional relational and document-oriented approaches. Our future roadmap focuses on three key areas:

### 更规范的类SQL语法支持 (Enhanced SQL-like Syntax Support)
We are working towards implementing more standardized SQL-like syntax to make SQL writing more intuitive and accessible. This will enable developers to leverage familiar SQL patterns while working with document data, reducing the learning curve and improving productivity.

### 结构化与非结构化数据快速转化 (Rapid Structured/Unstructured Data Conversion)
A core focus of our development is enabling seamless and rapid conversion between structured and unstructured document formats. This capability will allow applications to dynamically adapt their data models and easily migrate between different data representation approaches as requirements evolve.

### 混合存储模式支持 (Hybrid Storage Mode Support)
DocumentDB aims to simultaneously support both structured and unstructured storage paradigms within the same database system. This hybrid approach will provide users with maximum flexibility in choosing the most appropriate storage strategy for their specific use cases, whether they need the schema flexibility of document storage or the consistency guarantees of relational structures.

These enhancements will position DocumentDB as a truly versatile database engine capable of handling diverse data management scenarios while maintaining the reliability and performance characteristics of PostgreSQL.
