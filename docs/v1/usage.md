
## Usage

Once you have your `DocumentDB` set up running, you can start with creating collections, indexes and perform queries on them.

### Create a collection

DocumentDB provides [documentdb_api.create_collection](https://github.com/microsoft/documentdb/wiki/Functions#create_collection) function to create a new collection within a specified database, enabling you to manage and organize your BSON documents effectively.

```sql
SELECT documentdb_api.create_collection('documentdb','patient');
```

### Perform CRUD operations

#### Insert documents

The [documentdb_api.insert_one](https://github.com/microsoft/documentdb/wiki/Functions#insert_one) command is used to add a single document into a collection.

```sql
select documentdb_api.insert_one('documentdb','patient', '{ "patient_id": "P001", "name": "Alice Smith", "age": 30, "phone_number": "555-0123", "registration_year": "2023","conditions": ["Diabetes", "Hypertension"]}');
select documentdb_api.insert_one('documentdb','patient', '{ "patient_id": "P002", "name": "Bob Johnson", "age": 45, "phone_number": "555-0456", "registration_year": "2023", "conditions": ["Asthma"]}');
select documentdb_api.insert_one('documentdb','patient', '{ "patient_id": "P003", "name": "Charlie Brown", "age": 29, "phone_number": "555-0789", "registration_year": "2024", "conditions": ["Allergy", "Anemia"]}');
select documentdb_api.insert_one('documentdb','patient', '{ "patient_id": "P004", "name": "Diana Prince", "age": 40, "phone_number": "555-0987", "registration_year": "2024", "conditions": ["Migraine"]}');
select documentdb_api.insert_one('documentdb','patient', '{ "patient_id": "P005", "name": "Edward Norton", "age": 55, "phone_number": "555-1111", "registration_year": "2025", "conditions": ["Hypertension", "Heart Disease"]}');
```

#### Read document from a collection

The `documentdb_api.collection` function is used for retrieving the documents in a collection.

```sql
SELECT document FROM documentdb_api.collection('documentdb','patient');
```

Alternatively, we can apply filter to our queries.

```sql
SET search_path TO documentdb_api, documentdb_core;
SET documentdb_core.bsonUseEJson TO true;

SELECT cursorPage FROM documentdb_api.find_cursor_first_page('documentdb', '{ "find" : "patient", "filter" : {"patient_id":"P005"}}');
```

We can perform range queries as well.

```sql
SELECT cursorPage FROM documentdb_api.find_cursor_first_page('documentdb', '{ "find" : "patient", "filter" : { "$and": [{ "age": { "$gte": 10 } },{ "age": { "$lte": 35 } }] }}');
```

#### Update document in a collection

DocumentDB uses the [documentdb_api.update](https://github.com/microsoft/documentdb/wiki/Functions#update) function to modify existing documents within a collection.

The SQL command updates the `age` for patient `P004`.

```sql
select documentdb_api.update('documentdb', '{"update":"patient", "updates":[{"q":{"patient_id":"P004"},"u":{"$set":{"age":14}}}]}');
```

Similarly, we can update multiple documents using `multi` property.

```sql
SELECT documentdb_api.update('documentdb', '{"update":"patient", "updates":[{"q":{},"u":{"$set":{"age":24}},"multi":true}]}');
```

#### Delete document from the collection

DocumentDB uses the [documentdb_api.delete](https://github.com/microsoft/documentdb/wiki/Functions#delete) function for precise document removal based on specified criteria.

The SQL command deletes the document for patient `P002`.

```sql
SELECT documentdb_api.delete('documentdb', '{"delete": "patient", "deletes": [{"q": {"patient_id": "P002"}, "limit": 1}]}');
```

### 批量写入操作 (Bulk Write Operations)

DocumentDB provides bulk write operations for efficient processing of multiple documents in a single command. These operations are designed for high-performance scenarios where you need to insert or update many documents at once.

#### 批量插入 (Bulk Insert)

The [documentdb_api.insert_bulk](https://github.com/microsoft/documentdb/wiki/Functions#insert_bulk) procedure allows you to insert multiple documents in a single operation. This is significantly more efficient than individual insert operations for large datasets.

**Syntax:**
```sql
CALL documentdb_api.insert_bulk(
    p_database_name text,
    p_insert bson,
    p_insert_documents bsonsequence DEFAULT NULL,
    p_result INOUT bson DEFAULT NULL,
    p_success INOUT boolean DEFAULT NULL
);
```

**Example - Basic bulk insert:**
```sql
CALL documentdb_api.insert_bulk('documentdb', 
    '{"insert": "patient", "documents": [
        {"patient_id": "P006", "name": "Frank Miller", "age": 35, "conditions": ["Diabetes"]},
        {"patient_id": "P007", "name": "Grace Lee", "age": 28, "conditions": ["Asthma"]},
        {"patient_id": "P008", "name": "Henry Wilson", "age": 42, "conditions": ["Hypertension"]}
    ]}');
```

**Example - Bulk insert with ordered execution:**
```sql
CALL documentdb_api.insert_bulk('documentdb', 
    '{"insert": "patient", "documents": [
        {"patient_id": "P009", "name": "Ivy Chen", "age": 31},
        {"patient_id": "P010", "name": "Jack Brown", "age": 39}
    ], "ordered": true}');
```

#### 批量更新 (Bulk Update)

The [documentdb_api.update_bulk](https://github.com/microsoft/documentdb/wiki/Functions#update_bulk) procedure enables you to perform multiple update operations in a single command, supporting both single and multi-document updates.

**Syntax:**
```sql
CALL documentdb_api.update_bulk(
    p_database_name text,
    p_update bson,
    p_insert_documents bsonsequence DEFAULT NULL,
    p_transaction_id text DEFAULT NULL,
    p_result INOUT bson DEFAULT NULL,
    p_success INOUT boolean DEFAULT NULL
);
```

**Example - Basic bulk update:**
```sql
CALL documentdb_api.update_bulk('documentdb', 
    '{"update": "patient", "updates": [
        {"q": {"patient_id": "P006"}, "u": {"$set": {"age": 36}}},
        {"q": {"patient_id": "P007"}, "u": {"$set": {"age": 29}}}
    ]}');
```

**Example - Bulk update with multi-document operations:**
```sql
CALL documentdb_api.update_bulk('documentdb', 
    '{"update": "patient", "updates": [
        {"q": {"age": {"$lt": 30}}, "u": {"$set": {"category": "young"}}, "multi": true},
        {"q": {"age": {"$gte": 40}}, "u": {"$set": {"category": "senior"}}, "multi": true}
    ]}');
```

#### 重要限制和注意事项 (Important Limitations and Notes)

**批量大小限制 (Batch Size Limits):**
- Maximum batch size: **25,000 operations** per bulk command
- Exceeding this limit will result in an error: `Write batch sizes must be between 1 and 25000`

**事务限制 (Transaction Limitations):**
- Bulk write procedures **cannot be used within transactions**
- Use the corresponding functions instead of procedures when working within transactions
- Error message: `"the bulk insert/update procedure cannot be used in transactions"`

**执行模式 (Execution Modes):**
- **Ordered execution** (`"ordered": true`): Operations are executed sequentially, stopping on first error
- **Unordered execution** (`"ordered": false`, default): Operations may be executed in parallel, continuing after errors

**错误处理示例 (Error Handling Examples):**

```sql
-- Example of batch size limit error
CALL documentdb_api.insert_bulk('documentdb', 
    '{"insert": "patient", "documents": [/* 25001 documents */]}');
-- ERROR: Write batch sizes must be between 1 and 25000. Got 25001 operations.

-- Example of successful bulk operation with result
CALL documentdb_api.update_bulk('documentdb', 
    '{"update": "patient", "updates": [
        {"q": {"patient_id": "P006"}, "u": {"$set": {"updated": true}}}
    ]}');
-- Result: {"ok": 1.0, "nModified": 1, "n": 1}
```

**性能建议 (Performance Recommendations):**
- Use bulk operations for inserting/updating more than 10 documents at once
- Consider using unordered execution for better performance when order doesn't matter
- Monitor batch sizes to stay within the 25,000 operation limit
- Use appropriate indexes on filter fields for bulk update operations
