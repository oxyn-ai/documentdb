# DocumentDB 源程序鉴别材料

**软件名称：DocumentDB 版本号：0.105-0**

---

## 文档格式说明

- 页数：前30页 + 后30页，共60页
- 每页行数：不少于50行（结束页除外）
- 字体：宋体小五号
- 页边距：上下左右各2cm
- 行间距：单倍行距
- 页眉格式：软件名称：DocumentDB 版本号：0.105-0
- 页码：页面右上角，格式"第X页 共60页"

---

## 第1页 共60页

### 主程序入口 - main.rs

```rust
use log::info;
use simple_logger::SimpleLogger;
use std::{env, path::PathBuf, sync::Arc};
use documentdb_gateway::{
    configuration::{DocumentDBSetupConfiguration, PgConfiguration, SetupConfiguration},
    get_service_context, populate_ssl_certificates,
    postgres::{create_query_catalog, ConnectionPool, DocumentDBDataClient},
    run_server,
    shutdown_controller::SHUTDOWN_CONTROLLER,
    AUTHENTICATION_MAX_CONNECTIONS, SYSTEM_REQUESTS_MAX_CONNECTIONS,
};
use tokio::signal;
#[ntex::main]
async fn main() {
    let cfg_file = if let Some(arg1) = env::args().nth(1) {
        PathBuf::from(arg1)
    } else {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("SetupConfiguration.json")
    };
    let shutdown_token = SHUTDOWN_CONTROLLER.token();
    tokio::spawn(async move {
        signal::ctrl_c().await.expect("Failed to listen for Ctrl+C");
        info!("Ctrl+C received. Shutting down Rust gateway.");
        SHUTDOWN_CONTROLLER.shutdown();
    });
    let setup_configuration = DocumentDBSetupConfiguration::new(&cfg_file)
        .await
        .expect("Failed to load configuration.");
    info!("Starting server with configuration: {:?}", setup_configuration);
    SimpleLogger::new()
        .with_level(log::LevelFilter::Info)
        .with_module_level("tokio_postgres", log::LevelFilter::Info)
        .init()
        .expect("Failed to start logger");
    let query_catalog = create_query_catalog();
    let postgres_system_user = setup_configuration.postgres_system_user();
    let system_requests_pool = Arc::new(
        ConnectionPool::new_with_user(
            &setup_configuration,
            &query_catalog,
            &postgres_system_user,
            None,
            format!("{}-SystemRequests", setup_configuration.application_name()),
            SYSTEM_REQUESTS_MAX_CONNECTIONS,
        )
        .expect("Failed to create system requests pool"),
    );
    log::trace!("System requests pool initialized");
    let dynamic_configuration = PgConfiguration::new(
        &query_catalog,
        &setup_configuration,
        &system_requests_pool,
        "documentdb.",
    )
    .await
    .unwrap();
    let certificate_options = if let Some(co) = setup_configuration.certificate_options() {
        co
    } else {
        populate_ssl_certificates().await.unwrap()
    };
    let authentication_pool = ConnectionPool::new_with_user(
        &setup_configuration,
        &query_catalog,
        &postgres_system_user,
        None,
        format!("{}-PreAuthRequests", setup_configuration.application_name()),
        AUTHENTICATION_MAX_CONNECTIONS,
    )
    .expect("Failed to create authentication pool");
    log::trace!("Authentication pool initialized");
    let service_context = get_service_context(
        Box::new(setup_configuration),
        dynamic_configuration,
        query_catalog,
        system_requests_pool,
        authentication_pool,
    );
    run_server::<DocumentDBDataClient>(
        service_context,
        certificate_options,
        None,
        shutdown_token,
        None,
    )
    .await
    .unwrap();
}
```

## 第2页 共60页

### 身份验证模块 - auth.rs

```rust
use std::{str::from_utf8, sync::Arc};
use bson::{rawdoc, spec::BinarySubtype};
use rand::{distributions::Uniform, prelude::Distribution, rngs::OsRng};
use tokio_postgres::types::Type;
use crate::{
    context::ConnectionContext,
    error::{DocumentDBError, ErrorCode, Result},
    postgres::{PgDataClient, PgDocument},
    processor,
    protocol::OK_SUCCEEDED,
    requests::{Request, RequestInfo, RequestType},
    responses::{RawResponse, Response},
};
const NONCE_LENGTH: usize = 2;
pub struct ScramFirstState {
    nonce: String,
    first_message_bare: String,
    first_message: String,
}
pub struct AuthState {
    pub authorized: bool,
    first_state: Option<ScramFirstState>,
    username: Option<String>,
    pub password: Option<String>,
    user_oid: Option<u32>,
}
impl Default for AuthState {
    fn default() -> Self {
        Self::new()
    }
}
impl AuthState {
    pub fn new() -> Self {
        AuthState {
            authorized: false,
            first_state: None,
            username: None,
            password: None,
            user_oid: None,
        }
    }
    pub fn username(&self) -> Result<&str> {
        self.username
            .as_deref()
            .ok_or(DocumentDBError::internal_error(
                "Username missing".to_string(),
            ))
    }
    pub fn user_oid(&self) -> Result<u32> {
        self.user_oid.ok_or(DocumentDBError::internal_error(
            "User OID missing".to_string(),
        ))
    }
    pub fn set_username(&mut self, user: &str) {
        self.username = Some(user.to_string());
    }
    pub fn set_user_oid(&mut self, user_oid: u32) {
        self.user_oid = Some(user_oid);
    }
}
pub async fn process<T>(
    connection_context: &mut ConnectionContext,
    request: &Request<'_>,
) -> Result<Response>
where
    T: PgDataClient,
{
    if let Some(response) = handle_auth_request(connection_context, request).await? {
        return Ok(response);
    }
    let request_info = request.extract_common();
    if request.request_type().allowed_unauthorized() {
        let service_context = Arc::clone(&connection_context.service_context);
        let data_client = T::new_unauthorized(&service_context).await?;
        return processor::process_request(
            request,
            &mut request_info?,
            connection_context,
            data_client,
        )
        .await;
    }
    Err(DocumentDBError::unauthorized(format!(
        "Command {} not supported prior to authentication.",
        request.request_type().to_string().to_lowercase()
    )))
}
async fn handle_auth_request(
    connection_context: &mut ConnectionContext,
    request: &Request<'_>,
) -> Result<Option<Response>> {
    match request.request_type() {
        RequestType::SaslStart => Ok(Some(handle_sasl_start(connection_context, request).await?)),
        RequestType::SaslContinue => Ok(Some(
            handle_sasl_continue(connection_context, request).await?,
        )),
        RequestType::Logout => {
            connection_context.auth_state = AuthState::new();
            Ok(Some(Response::Raw(RawResponse(rawdoc! {
                "ok": OK_SUCCEEDED,
            }))))
        }
        _ => Ok(None),
    }
}
```

## 第3页 共60页

### SCRAM-SHA-256 认证实现

```rust
async fn handle_sasl_start(
    connection_context: &mut ConnectionContext,
    request: &Request<'_>,
) -> Result<Response> {
    let mechanism = request
        .document()
        .get_str("mechanism")
        .map_err(DocumentDBError::parse_failure())?;
    if mechanism != "SCRAM-SHA-256" {
        return Err(DocumentDBError::unauthorized(
            "Only SCRAM-SHA-256 is supported".to_string(),
        ));
    }
    let payload = parse_sasl_payload(request, true)?;
    let username = payload.username.ok_or(DocumentDBError::unauthorized(
        "Username missing from SaslStart.".to_string(),
    ))?;
    let client_nonce = payload.nonce.ok_or(DocumentDBError::unauthorized(
        "Nonce missing from SaslStart.".to_string(),
    ))?;
    let mut nonce = String::with_capacity(client_nonce.len() + NONCE_LENGTH);
    nonce.push_str(client_nonce);
    nonce.extend(
        Uniform::from(33..125)
            .sample_iter(OsRng)
            .map(|x: u8| if x > 43 { (x + 1) as char } else { x as char })
            .take(NONCE_LENGTH),
    );
    let (salt, iterations) = get_salt_and_iteration(connection_context, username).await?;
    let response = format!("r={},s={},i={}", nonce, salt, iterations);
    connection_context.auth_state.first_state = Some(ScramFirstState {
        nonce,
        first_message_bare: format!("n={},r={}", username, client_nonce),
        first_message: response.clone(),
    });
    connection_context.auth_state.username = Some(username.to_string());
    let binary_response = bson::Binary {
        subtype: BinarySubtype::Generic,
        bytes: response.as_bytes().to_vec(),
    };
    Ok(Response::Raw(RawResponse(rawdoc! {
        "payload": binary_response,
        "ok": OK_SUCCEEDED,
        "conversationId": 1,
        "done": false
    })))
}
async fn handle_sasl_continue(
    connection_context: &mut ConnectionContext,
    request: &Request<'_>,
) -> Result<Response> {
    let payload = parse_sasl_payload(request, false)?;
    if let Some(first_state) = connection_context.auth_state.first_state.as_ref() {
        let client_nonce = payload.nonce.ok_or(DocumentDBError::unauthorized(
            "Nonce missing from SaslContinue.".to_string(),
        ))?;
        let proof = payload.proof.ok_or(DocumentDBError::unauthorized(
            "Proof missing from SaslContinue.".to_string(),
        ))?;
        let channel_binding = payload
            .channel_binding
            .ok_or(DocumentDBError::unauthorized(
                "Channel binding missing from SaslContinue.".to_string(),
            ))?;
        let username = payload
            .username
            .or(connection_context.auth_state.username.as_deref())
            .ok_or(DocumentDBError::internal_error(
                "Username missing from sasl continue".to_string(),
            ))?;
        if client_nonce != first_state.nonce {
            return Err(DocumentDBError::unauthorized(
                "Nonce did not match expected nonce.".to_string(),
            ));
        }
        let auth_message = format!(
            "{},{},c={},r={}",
            first_state.first_message_bare,
            first_state.first_message,
            channel_binding,
            client_nonce
        );
        let scram_sha256_row = connection_context
            .service_context
            .authentication_connection()
            .await?
            .query(
                connection_context
                    .service_context
                    .query_catalog()
                    .authenticate_with_scram_sha256(),
                &[Type::TEXT, Type::TEXT, Type::TEXT],
                &[&username, &auth_message, &proof],
                None,
                &mut RequestInfo::new(),
            )
            .await?;
        let scram_sha256_doc: PgDocument = scram_sha256_row
            .first()
            .ok_or(DocumentDBError::pg_response_empty())?
            .try_get(0)?;
        if scram_sha256_doc
            .0
            .get_i32("ok")
            .map_err(DocumentDBError::pg_response_invalid)?
            != 1
        {
            return Err(DocumentDBError::unauthorized("Invalid key".to_string()));
        }
        let server_signature = scram_sha256_doc
            .0
            .get_str("ServerSignature")
            .map_err(DocumentDBError::pg_response_invalid)?;
        let payload = bson::Binary {
            subtype: BinarySubtype::Generic,
            bytes: format!("v={}", server_signature).as_bytes().to_vec(),
        };
        connection_context.auth_state.password = Some("".to_string());
        connection_context.auth_state.user_oid =
            Some(get_user_oid(connection_context, username).await?);
        connection_context.auth_state.authorized = true;
        Ok(Response::Raw(RawResponse(rawdoc! {
            "payload": payload,
            "ok": OK_SUCCEEDED,
            "conversationId": 1,
            "done": true
        })))
    } else {
        Err(DocumentDBError::unauthorized(
            "Sasl Continue called without SaslStart state.".to_string(),
        ))
    }
}
```

## 第4页 共60页

### BSON核心功能 - pgbson.c

```c
#include <postgres.h>
#include <utils/builtins.h>
#include <lib/stringinfo.h>
#include <utils/timestamp.h>
#define PRIVATE_PGBSON_H
#include "io/pgbson.h"
#include "io/pgbson_writer.h"
#undef PRIVATE_PGBSON_H
#include "io/bsonvalue_utils.h"
#include "utils/documentdb_errors.h"
#include "utils/string_view.h"
static pgbson * CreatePgbsonfromBson_t(bson_t *document, bool destroyDocument);
static pgbson * CreatePgbsonfromBsonBytes(const uint8_t *rawbytes, uint32_t length);
static const char *BsonHexPrefix = "BSONHEX";
static const uint32_t BsonHexPrefixLength = 7;
bool
PgbsonEquals(const pgbson *left, const pgbson *right)
{
    if (left == NULL || right == NULL)
    {
        if (left == NULL && right == NULL)
        {
            return true;
        }
        return false;
    }
    if (VARSIZE_ANY_EXHDR(left) != VARSIZE_ANY_EXHDR(right))
    {
        return false;
    }
    return memcmp(VARDATA_ANY(left), VARDATA_ANY(right), VARSIZE_ANY_EXHDR(left)) == 0;
}
int
PgbsonCountKeys(const pgbson *bsonDocument)
{
    bson_t bson;
    if (!bson_init_static(&bson, (const uint8_t *) VARDATA_ANY(bsonDocument),
                          VARSIZE_ANY_EXHDR(bsonDocument)))
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                        errmsg("invalid input syntax for BSON")));
    }
    return bson_count_keys(&bson);
}
int
BsonDocumentValueCountKeys(const bson_value_t *value)
{
    if (value->value_type != BSON_TYPE_ARRAY && value->value_type != BSON_TYPE_DOCUMENT)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                        errmsg("Expected value of type array or document")));
    }
    bson_t bson;
    if (!bson_init_static(&bson, value->value.v_doc.data,
                          value->value.v_doc.data_len))
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                        errmsg("invalid input syntax for BSON")));
    }
    return bson_count_keys(&bson);
}
uint32_t
PgbsonGetBsonSize(const pgbson *bson)
{
    return VARSIZE_ANY_EXHDR(bson);
}
bool
IsBsonHexadecimalString(const char *string)
{
    return string[0] == BsonHexPrefix[0];
}
pgbson *
PgbsonInitFromHexadecimalString(const char *hexadecimalString)
{
    uint32_t strLength = strlen(hexadecimalString);
    uint32_t hexStringLength = (strLength - BsonHexPrefixLength);
    if (hexStringLength <= 0 || (hexStringLength % 2 != 0))
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE), errmsg(
                            "Invalid Hex string for pgbson input")));
    }
    if (strncmp(hexadecimalString, BsonHexPrefix, BsonHexPrefixLength) != 0)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                        errmsg("Bson Hex string does not have valid prefix %s",
                               BsonHexPrefix)));
    }
    uint32_t binaryLength = hexStringLength / 2;
    int allocSize = binaryLength + VARHDRSZ;
    pgbson *pgbsonVal = (pgbson *) palloc(allocSize);
    uint64 actualBinarySize = hex_decode(&hexadecimalString[BsonHexPrefixLength],
                                         hexStringLength, VARDATA(pgbsonVal));
    Assert(actualBinarySize == binaryLength);
    SET_VARSIZE(pgbsonVal, (uint32_t) actualBinarySize + VARHDRSZ);
    return pgbsonVal;
}
const char *
PgbsonToHexadecimalString(const pgbson *bsonDocument)
{
    size_t binarySize = VARSIZE_ANY_EXHDR(bsonDocument);
    size_t hexEncodedSize = binarySize * 2;
    size_t hexStringSize = hexEncodedSize + 1 + BsonHexPrefixLength;
    char *hexString = palloc(hexStringSize);
    memcpy(hexString, BsonHexPrefix, BsonHexPrefixLength);
    const char *pgbsonData = VARDATA_ANY(bsonDocument);
    uint64 hexStringActualSize = hex_encode(pgbsonData, binarySize,
                                            &hexString[BsonHexPrefixLength]);
    Assert(hexStringActualSize == hexEncodedSize);
    hexString[hexStringActualSize + BsonHexPrefixLength] = 0;
    return hexString;
}
pgbson *
PgbsonInitFromJson(const char *jsonString)
{
    bson_t bson;
    bson_error_t error;
    bool parseResult = bson_init_from_json(&bson, jsonString, -1, &error);
    if (!parseResult)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE), errmsg(
                            "invalid input syntax JSON for BSON: Code: '%d', Message '%s'",
                            error.code, error.message)));
    }
    return CreatePgbsonfromBson_t(&bson, true);
}
const char *
PgbsonToJsonForLogging(const pgbson *bsonDocument)
{
    bson_t bson;
    if (!bson_init_static(&bson, (uint8_t *) VARDATA_ANY(bsonDocument),
                          (uint32_t) VARSIZE_ANY_EXHDR(bsonDocument)))
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                        errmsg("invalid input syntax for BSON")));
    }
    return bson_as_relaxed_extended_json(&bson, NULL);
}
```

## 第5页 共60页

### PostgreSQL扩展API - insert.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <funcapi.h>
#include <nodes/makefuncs.h>
#include <utils/timestamp.h>
#include <utils/portal.h>
#include <tcop/dest.h>
#include <tcop/pquery.h>
#include <tcop/tcopprot.h>
#include <commands/portalcmds.h>
#include <utils/snapmgr.h>
#include <catalog/pg_class.h>
#include <parser/parse_relation.h>
#include <utils/lsyscache.h>
#include "access/xact.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "utils/builtins.h"
#include "io/bson_core.h"
#include "commands/commands_common.h"
#include "commands/insert.h"
#include "commands/parse_error.h"
#include "metadata/collection.h"
#include "infrastructure/documentdb_plan_cache.h"
#include "sharding/sharding.h"
#include "commands/retryable_writes.h"
#include "io/pgbsonsequence.h"
#include "utils/query_utils.h"
#include "utils/feature_counter.h"
#include "metadata/metadata_cache.h"
#include "utils/error_utils.h"
#include "utils/version_utils.h"
#include "utils/documentdb_errors.h"
#include "api_hooks.h"
#include "schema_validation/schema_validation.h"
#include "operators/bson_expr_eval.h"
typedef struct BatchInsertionSpec
{
    char *collectionName;
    List *documents;
    bool isOrdered;
    Oid insertShardOid;
    bool bypassDocumentValidation;
} BatchInsertionSpec;
typedef struct BatchInsertionResult
{
    double ok;
    uint64 rowsInserted;
    List *writeErrors;
    MemoryContext resultMemoryContext;
} BatchInsertionResult;
PG_FUNCTION_INFO_V1(command_insert);
PG_FUNCTION_INFO_V1(command_insert_one);
PG_FUNCTION_INFO_V1(command_insert_worker);
PG_FUNCTION_INFO_V1(command_insert_bulk);
static BatchInsertionSpec * BuildBatchInsertionSpec(bson_iter_t *insertCommandIter,
                                                    pgbsonsequence *insertDocs);
static List * BuildInsertionList(bson_iter_t *insertArrayIter, bool *hasSkippedDocuments);
static List * BuildInsertionListFromPgbsonSequence(pgbsonsequence *docSequence,
                                                   bool *hasSkippedDocuments);
static BatchInsertionResult * ProcessBatchInsertion(BatchInsertionSpec *insertionSpec,
                                                    const char *databaseName,
                                                    uint64 transactionId,
                                                    bool isRetryableWrite);
static BatchInsertionResult * DoBatchInsertNoTransactionId(BatchInsertionSpec *insertionSpec,
                                                           const char *databaseName,
                                                           bool isRetryableWrite,
                                                           bool isShardedCollection);
static void ProcessInsertion(const char *databaseName, const char *collectionName,
                            pgbson *document, bool bypassDocumentValidation);
static StringInfo CreateInsertQuery(const char *databaseName, const char *collectionName);
static pgbson * PreprocessInsertionDoc(pgbson *document, const char *databaseName,
                                       const char *collectionName,
                                       bool bypassDocumentValidation);
static void InsertOneWithTransactionCore(const char *databaseName, const char *collectionName,
                                        pgbson *document, bool bypassDocumentValidation);
static void CallInsertWorkerForInsertOne(const char *databaseName, const char *collectionName,
                                        pgbson *document);
static pgbson * CommandInsertCore(const char *databaseName, bson_iter_t *insertCommandIter);
static List * CreateValuesListForInsert(const char *databaseName, const char *collectionName,
                                       List *documents);
Datum
command_insert(PG_FUNCTION_ARGS)
{
    pgbson *insertCommand = PG_GETARG_PGBSON(0);
    const char *databaseName = PG_GETARG_CSTRING(1);
    return DirectFunctionCall2(command_bson_insert, PgbsonToDatum(insertCommand),
                              CStringGetDatum(databaseName));
}
Datum
command_insert_bulk(PG_FUNCTION_ARGS)
{
    pgbson *insertCommand = PG_GETARG_PGBSON(0);
    const char *databaseName = PG_GETARG_CSTRING(1);
    pgbsonsequence *insertDocs = PG_GETARG_PGBSONSEQUENCE(2);
    bson_iter_t insertCommandIter;
    PgbsonInitIterator(insertCommand, &insertCommandIter);
    BatchInsertionSpec *insertionSpec = BuildBatchInsertionSpec(&insertCommandIter, insertDocs);
    uint64 transactionId = GetCurrentTransactionIdIfAny();
    bool isRetryableWrite = IsRetryableWriteActive();
    BatchInsertionResult *insertionResult = ProcessBatchInsertion(insertionSpec,
                                                                 databaseName,
                                                                 transactionId,
                                                                 isRetryableWrite);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    PgbsonWriterAppendDouble(&writer, "ok", insertionResult->ok);
    PgbsonWriterAppendInt64(&writer, "n", insertionResult->rowsInserted);
    if (insertionResult->writeErrors != NIL)
    {
        PgbsonWriterStartArray(&writer, "writeErrors");
        ListCell *errorCell;
        foreach(errorCell, insertionResult->writeErrors)
        {
            pgbson *errorDocument = (pgbson *) lfirst(errorCell);
            PgbsonWriterAppendDocument(&writer, NULL, errorDocument);
        }
        PgbsonWriterEndArray(&writer);
    }
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
```

## 第6页 共60页

### 文档插入处理函数

```c
static bool
ValidateAndCheckShouldInsertDocument(pgbson *document, const char *databaseName,
                                   const char *collectionName, bool bypassDocumentValidation,
                                   bool isOrdered, int documentIndex, List **writeErrors,
                                   MemoryContext resultMemoryContext)
{
    bool shouldInsertDocument = true;
    if (!bypassDocumentValidation)
    {
        PG_TRY();
        {
            ValidateDocumentForInsertion(document, databaseName, collectionName);
        }
        PG_CATCH();
        {
            ErrorData *errorData = CopyErrorData();
            FlushErrorState();
            shouldInsertDocument = false;
            if (writeErrors != NULL)
            {
                MemoryContext oldContext = MemoryContextSwitchTo(resultMemoryContext);
                pgbson_writer errorWriter;
                PgbsonWriterInit(&errorWriter);
                PgbsonWriterAppendInt32(&errorWriter, "index", documentIndex);
                PgbsonWriterAppendInt32(&errorWriter, "code", errorData->sqlerrcode);
                PgbsonWriterAppendUtf8(&errorWriter, "errmsg", errorData->message);
                *writeErrors = lappend(*writeErrors, PgbsonWriterGetPgbson(&errorWriter));
                MemoryContextSwitchTo(oldContext);
            }
            FreeErrorData(errorData);
            if (isOrdered)
            {
                return shouldInsertDocument;
            }
        }
        PG_END_TRY();
    }
    return shouldInsertDocument;
}
static BatchInsertionResult *
DoMultiInsertWithoutTransactionId(BatchInsertionSpec *insertionSpec,
                                 const char *databaseName,
                                 bool isRetryableWrite,
                                 bool isShardedCollection)
{
    BatchInsertionResult *insertionResult = palloc0(sizeof(BatchInsertionResult));
    insertionResult->ok = 1.0;
    insertionResult->rowsInserted = 0;
    insertionResult->writeErrors = NIL;
    insertionResult->resultMemoryContext = CurrentMemoryContext;
    ListCell *documentCell;
    int documentIndex = 0;
    foreach(documentCell, insertionSpec->documents)
    {
        pgbson *document = (pgbson *) lfirst(documentCell);
        bool shouldInsertDocument = ValidateAndCheckShouldInsertDocument(
            document, databaseName, insertionSpec->collectionName,
            insertionSpec->bypassDocumentValidation, insertionSpec->isOrdered,
            documentIndex, &insertionResult->writeErrors,
            insertionResult->resultMemoryContext);
        if (shouldInsertDocument)
        {
            PG_TRY();
            {
                ProcessInsertion(databaseName, insertionSpec->collectionName,
                               document, insertionSpec->bypassDocumentValidation);
                insertionResult->rowsInserted++;
            }
            PG_CATCH();
            {
                ErrorData *errorData = CopyErrorData();
                FlushErrorState();
                MemoryContext oldContext = MemoryContextSwitchTo(
                    insertionResult->resultMemoryContext);
                pgbson_writer errorWriter;
                PgbsonWriterInit(&errorWriter);
                PgbsonWriterAppendInt32(&errorWriter, "index", documentIndex);
                PgbsonWriterAppendInt32(&errorWriter, "code", errorData->sqlerrcode);
                PgbsonWriterAppendUtf8(&errorWriter, "errmsg", errorData->message);
                insertionResult->writeErrors = lappend(insertionResult->writeErrors,
                                                     PgbsonWriterGetPgbson(&errorWriter));
                MemoryContextSwitchTo(oldContext);
                FreeErrorData(errorData);
                if (insertionSpec->isOrdered)
                {
                    break;
                }
            }
            PG_END_TRY();
        }
        documentIndex++;
    }
    return insertionResult;
}
```

## 第7页 共60页

### MongoDB聚合管道处理 - bson_aggregation_pipeline.c

```c
#include <postgres.h>
#include <float.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <optimizer/optimizer.h>
#include <access/table.h>
#include <access/reloptions.h>
#include <utils/rel.h>
#include <catalog/namespace.h>
#include <optimizer/planner.h>
#include <nodes/nodes.h>
#include <nodes/makefuncs.h>
#include <nodes/nodeFuncs.h>
#include <parser/parser.h>
#include <parser/parse_agg.h>
#include <parser/parse_clause.h>
#include <parser/parse_param.h>
#include <parser/analyze.h>
#include <parser/parse_oper.h>
#include <utils/ruleutils.h>
#include <utils/builtins.h>
#include <catalog/pg_aggregate.h>
#include <catalog/pg_operator.h>
#include <catalog/pg_class.h>
#include <parser/parsetree.h>
#include <utils/array.h>
#include <utils/builtins.h>
#include <utils/lsyscache.h>
#include <utils/numeric.h>
#include <utils/lsyscache.h>
#include <utils/fmgroids.h>
#include <nodes/supportnodes.h>
#include <parser/parse_relation.h>
#include <parser/parse_func.h>
#include "io/bson_core.h"
#include "metadata/metadata_cache.h"
#include "query/query_operator.h"
#include "planner/documentdb_planner.h"
#include "aggregation/bson_aggregation_pipeline.h"
#include "aggregation/bson_aggregation_window_operators.h"
#include "commands/parse_error.h"
#include "commands/commands_common.h"
#include "commands/defrem.h"
#include "utils/feature_counter.h"
#include "utils/version_utils.h"
#include "aggregation/bson_query.h"
#include "aggregation/bson_aggregation_pipeline_private.h"
#include "aggregation/bson_bucket_auto.h"
#include "api_hooks.h"
#include "vector/vector_common.h"
#include "aggregation/bson_project.h"
#include "operators/bson_expression.h"
#include "operators/bson_expression_operators.h"
#include "operators/bson_expression_bucket_operator.h"
#include "geospatial/bson_geospatial_common.h"
#include "geospatial/bson_geospatial_geonear.h"
#include "aggregation/bson_densify.h"
#include "collation/collation.h"
#include "api_hooks.h"
extern bool EnableCursorsOnAggregationQueryRewrite;
extern bool EnableCollation;
extern bool DefaultInlineWriteOperations;
extern bool EnableSortbyIdPushDownToPrimaryKey;
extern int MaxAggregationStagesAllowed;
extern bool EnableIndexOrderbyPushdown;
extern int TdigestCompressionAccuracy;
typedef Query *(*MutateQueryForStageFunc)(const bson_value_t *existingValue,
                                          Query *query,
                                          AggregationPipelineBuildContext *context);
typedef void (*PipelineStagesPreCheckFunc)(const bson_value_t *existingValue,
                                          const AggregationPipelineBuildContext *context);
typedef bool (*RequiresPersistentCursorFunc)(const bson_value_t *existingValue);
typedef struct AggregationStageDefinition
{
    const char *stageName;
    MutateQueryForStageFunc mutateQueryFunc;
    PipelineStagesPreCheckFunc preCheckFunc;
    RequiresPersistentCursorFunc requiresPersistentCursorFunc;
    bool canInlineLookupPipeline;
    bool canInlineUnionWithPipeline;
    bool isWriteStage;
    bool isChangeStreamCompatible;
    bool requiresShardKeyForUpdate;
    bool allowedInView;
    bool allowedInMaterializedView;
    bool allowedAfterOut;
    bool allowedAfterMerge;
    bool allowedInChangeStream;
    bool allowedInTransaction;
    bool allowedInLookupPipeline;
    bool allowedInFacetPipeline;
    bool allowedInUnionWithPipeline;
    bool allowedInGraphLookupPipeline;
    bool allowedInSetWindowFieldsPipeline;
    bool allowedInSearch;
    bool allowedInSearchMeta;
    bool allowedInVectorSearch;
    bool allowedInAtlas;
} AggregationStageDefinition;
PG_FUNCTION_INFO_V1(command_bson_aggregation_pipeline);
PG_FUNCTION_INFO_V1(command_api_collection);
PG_FUNCTION_INFO_V1(command_aggregation_support);
PG_FUNCTION_INFO_V1(documentdb_core_bson_to_bson);
Datum
command_bson_aggregation_pipeline(PG_FUNCTION_ARGS)
{
    pgbson *aggregationCommand = PG_GETARG_PGBSON(0);
    const char *databaseName = PG_GETARG_CSTRING(1);
    bson_iter_t aggregationCommandIter;
    PgbsonInitIterator(aggregationCommand, &aggregationCommandIter);
    const char *collectionName = NULL;
    const bson_value_t *pipelineValue = NULL;
    const bson_value_t *cursorValue = NULL;
    const bson_value_t *explainValue = NULL;
    const bson_value_t *allowDiskUseValue = NULL;
    const bson_value_t *maxTimeMSValue = NULL;
    const bson_value_t *bypassDocumentValidationValue = NULL;
    const bson_value_t *readConcernValue = NULL;
    const bson_value_t *collationValue = NULL;
    const bson_value_t *hintValue = NULL;
    const bson_value_t *commentValue = NULL;
    const bson_value_t *letValue = NULL;
    while (bson_iter_next(&aggregationCommandIter))
    {
        const char *key = bson_iter_key(&aggregationCommandIter);
        const bson_value_t *value = bson_iter_value(&aggregationCommandIter);
        if (strcmp(key, "aggregate") == 0)
        {
            if (value->value_type != BSON_TYPE_UTF8)
            {
                ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                               errmsg("collection name must be a string")));
            }
            collectionName = value->value.v_utf8.str;
        }
        else if (strcmp(key, "pipeline") == 0)
        {
            pipelineValue = value;
        }
        else if (strcmp(key, "cursor") == 0)
        {
            cursorValue = value;
        }
        else if (strcmp(key, "explain") == 0)
        {
            explainValue = value;
        }
        else if (strcmp(key, "allowDiskUse") == 0)
        {
            allowDiskUseValue = value;
        }
        else if (strcmp(key, "maxTimeMS") == 0)
        {
            maxTimeMSValue = value;
        }
        else if (strcmp(key, "bypassDocumentValidation") == 0)
        {
            bypassDocumentValidationValue = value;
        }
        else if (strcmp(key, "readConcern") == 0)
        {
            readConcernValue = value;
        }
        else if (strcmp(key, "collation") == 0)
        {
            collationValue = value;
        }
        else if (strcmp(key, "hint") == 0)
        {
            hintValue = value;
        }
        else if (strcmp(key, "comment") == 0)
        {
            commentValue = value;
        }
        else if (strcmp(key, "let") == 0)
        {
            letValue = value;
        }
    }
    if (collectionName == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("BSON field 'aggregate' is missing but a required field")));
    }
    if (pipelineValue == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("BSON field 'pipeline' is missing but a required field")));
    }
    if (pipelineValue->value_type != BSON_TYPE_ARRAY)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("'pipeline' option must be specified as an array")));
    }
    ValidateAggregationPipeline(pipelineValue);
    CheckMaxAllowedAggregationStages(pipelineValue);
    return GenerateAggregationQuery(databaseName, collectionName, pipelineValue,
                                   cursorValue, explainValue, allowDiskUseValue,
                                   maxTimeMSValue, bypassDocumentValidationValue,
                                   readConcernValue, collationValue, hintValue,
                                   commentValue, letValue);
}
```

## 第8页 共60页

### 聚合管道验证与处理

```c
static void
ValidateAggregationPipeline(const bson_value_t *pipelineValue)
{
    if (pipelineValue->value_type != BSON_TYPE_ARRAY)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("'pipeline' option must be specified as an array")));
    }
    bson_iter_t pipelineIter;
    BsonValueInitIterator(pipelineValue, &pipelineIter);
    int stageIndex = 0;
    while (bson_iter_next(&pipelineIter))
    {
        const bson_value_t *stageValue = bson_iter_value(&pipelineIter);
        if (stageValue->value_type != BSON_TYPE_DOCUMENT)
        {
            ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                           errmsg("Each element of the 'pipeline' array must be an object")));
        }
        bson_iter_t stageIter;
        BsonValueInitIterator(stageValue, &stageIter);
        if (!bson_iter_next(&stageIter))
        {
            ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                           errmsg("A pipeline stage specification object must contain exactly one field")));
        }
        const char *stageName = bson_iter_key(&stageIter);
        const bson_value_t *stageSpec = bson_iter_value(&stageIter);
        if (bson_iter_next(&stageIter))
        {
            ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                           errmsg("A pipeline stage specification object must contain exactly one field")));
        }
        const AggregationStageDefinition *stageDefinition = GetAggregationStageDefinition(stageName);
        if (stageDefinition == NULL)
        {
            ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_COMMANDNOTSUPPORTED),
                           errmsg("Unrecognized pipeline stage name: '%s'", stageName)));
        }
        if (stageDefinition->preCheckFunc != NULL)
        {
            AggregationPipelineBuildContext context = { 0 };
            context.stageIndex = stageIndex;
            context.databaseName = NULL;
            context.collectionName = NULL;
            stageDefinition->preCheckFunc(stageSpec, &context);
        }
        stageIndex++;
    }
}
static void
CheckMaxAllowedAggregationStages(const bson_value_t *pipelineValue)
{
    bson_iter_t pipelineIter;
    BsonValueInitIterator(pipelineValue, &pipelineIter);
    int stageCount = 0;
    while (bson_iter_next(&pipelineIter))
    {
        stageCount++;
    }
    if (stageCount > MaxAggregationStagesAllowed)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("Pipeline exceeds maximum allowed stages (%d)",
                              MaxAggregationStagesAllowed)));
    }
}
static Query *
MutateQueryWithPipeline(Query *query, const bson_value_t *pipelineValue,
                       AggregationPipelineBuildContext *context)
{
    bson_iter_t pipelineIter;
    BsonValueInitIterator(pipelineValue, &pipelineIter);
    int stageIndex = 0;
    while (bson_iter_next(&pipelineIter))
    {
        const bson_value_t *stageValue = bson_iter_value(&pipelineIter);
        bson_iter_t stageIter;
        BsonValueInitIterator(stageValue, &stageIter);
        bson_iter_next(&stageIter);
        const char *stageName = bson_iter_key(&stageIter);
        const bson_value_t *stageSpec = bson_iter_value(&stageIter);
        const AggregationStageDefinition *stageDefinition = GetAggregationStageDefinition(stageName);
        if (stageDefinition == NULL)
        {
            ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_COMMANDNOTSUPPORTED),
                           errmsg("Unrecognized pipeline stage name: '%s'", stageName)));
        }
        context->stageIndex = stageIndex;
        if (stageDefinition->mutateQueryFunc != NULL)
        {
            query = stageDefinition->mutateQueryFunc(stageSpec, query, context);
        }
        stageIndex++;
    }
    return query;
}
static Query *
HandleMatchAggregationStage(const bson_value_t *matchSpec, Query *query,
                           AggregationPipelineBuildContext *context)
{
    if (matchSpec->value_type != BSON_TYPE_DOCUMENT)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("$match stage specification must be a document")));
    }
    Node *whereClause = BsonValueToQueryOperatorExpression(matchSpec, context);
    if (query->jointree->quals == NULL)
    {
        query->jointree->quals = whereClause;
    }
    else
    {
        query->jointree->quals = (Node *) makeBoolExpr(AND_EXPR,
                                                      list_make2(query->jointree->quals,
                                                                whereClause),
                                                      -1);
    }
    return query;
}
```

## 第9页 共60页

### 查询处理与优化

```c
static Query *
HandleProject(const bson_value_t *projectSpec, Query *query,
             AggregationPipelineBuildContext *context)
{
    if (projectSpec->value_type != BSON_TYPE_DOCUMENT)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("$project stage specification must be a document")));
    }
    List *targetList = NIL;
    bson_iter_t projectIter;
    BsonValueInitIterator(projectSpec, &projectIter);
    while (bson_iter_next(&projectIter))
    {
        const char *fieldName = bson_iter_key(&projectIter);
        const bson_value_t *fieldSpec = bson_iter_value(&projectIter);
        TargetEntry *targetEntry = CreateProjectionTargetEntry(fieldName, fieldSpec, context);
        targetList = lappend(targetList, targetEntry);
    }
    query->targetList = targetList;
    return query;
}
static Query *
HandleSort(const bson_value_t *sortSpec, Query *query,
          AggregationPipelineBuildContext *context)
{
    if (sortSpec->value_type != BSON_TYPE_DOCUMENT)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("$sort stage specification must be a document")));
    }
    List *sortClause = NIL;
    bson_iter_t sortIter;
    BsonValueInitIterator(sortSpec, &sortIter);
    while (bson_iter_next(&sortIter))
    {
        const char *fieldName = bson_iter_key(&sortIter);
        const bson_value_t *sortDirection = bson_iter_value(&sortIter);
        SortBy *sortBy = CreateSortByClause(fieldName, sortDirection, context);
        sortClause = lappend(sortClause, sortBy);
    }
    query->sortClause = sortClause;
    return query;
}
static Query *
HandleLimit(const bson_value_t *limitSpec, Query *query,
           AggregationPipelineBuildContext *context)
{
    if (limitSpec->value_type != BSON_TYPE_INT32 && limitSpec->value_type != BSON_TYPE_INT64)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("$limit stage specification must be a number")));
    }
    int64 limitValue;
    if (limitSpec->value_type == BSON_TYPE_INT32)
    {
        limitValue = limitSpec->value.v_int32;
    }
    else
    {
        limitValue = limitSpec->value.v_int64;
    }
    if (limitValue < 0)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("$limit stage specification must be a non-negative number")));
    }
    query->limitCount = (Node *) makeConst(INT8OID, -1, InvalidOid, sizeof(int64),
                                          Int64GetDatum(limitValue), false, FLOAT8PASSBYVAL);
    return query;
}
static Query *
HandleSkip(const bson_value_t *skipSpec, Query *query,
          AggregationPipelineBuildContext *context)
{
    if (skipSpec->value_type != BSON_TYPE_INT32 && skipSpec->value_type != BSON_TYPE_INT64)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("$skip stage specification must be a number")));
    }
    int64 skipValue;
    if (skipSpec->value_type == BSON_TYPE_INT32)
    {
        skipValue = skipSpec->value.v_int32;
    }
    else
    {
        skipValue = skipSpec->value.v_int64;
    }
    if (skipValue < 0)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("$skip stage specification must be a non-negative number")));
    }
    query->limitOffset = (Node *) makeConst(INT8OID, -1, InvalidOid, sizeof(int64),
                                           Int64GetDatum(skipValue), false, FLOAT8PASSBYVAL);
    return query;
}
static Query *
HandleGroup(const bson_value_t *groupSpec, Query *query,
           AggregationPipelineBuildContext *context)
{
    if (groupSpec->value_type != BSON_TYPE_DOCUMENT)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("$group stage specification must be a document")));
    }
    List *groupClause = NIL;
    List *targetList = NIL;
    bson_iter_t groupIter;
    BsonValueInitIterator(groupSpec, &groupIter);
    while (bson_iter_next(&groupIter))
    {
        const char *fieldName = bson_iter_key(&groupIter);
        const bson_value_t *fieldSpec = bson_iter_value(&groupIter);
        if (strcmp(fieldName, "_id") == 0)
        {
            if (fieldSpec->value_type != BSON_TYPE_NULL)
            {
                GroupingSet *groupingSet = CreateGroupingSetFromSpec(fieldSpec, context);
                groupClause = lappend(groupClause, groupingSet);
            }
        }
        else
        {
            TargetEntry *targetEntry = CreateGroupAccumulatorTargetEntry(fieldName, fieldSpec, context);
            targetList = lappend(targetList, targetEntry);
        }
    }
    query->groupClause = groupClause;
    query->targetList = list_concat(query->targetList, targetList);
    query->hasAggs = true;
    return query;
}
```

## 第10页 共60页

### 文档查找与修改 - find_and_modify.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <storage/lockdefs.h>
#include <utils/builtins.h>
#include <funcapi.h>
#include "io/bson_core.h"
#include "update/bson_update.h"
#include "commands/commands_common.h"
#include "commands/delete.h"
#include "commands/insert.h"
#include "utils/documentdb_errors.h"
#include "commands/parse_error.h"
#include "commands/update.h"
#include "metadata/collection.h"
#include "query/query_operator.h"
#include "sharding/sharding.h"
#include "utils/feature_counter.h"
#include "schema_validation/schema_validation.h"
typedef struct
{
    char *collectionName;
    bson_value_t *query;
    bson_value_t *sort;
    bool remove;
    bson_value_t *update;
    bson_value_t *arrayFilters;
    bool returnNewDocument;
    bson_value_t *returnFields;
    bool upsert;
    bool bypassDocumentValidation;
} FindAndModifySpec;
typedef struct
{
    bool isUpdateCommand;
    struct
    {
        unsigned int n;
        bool updatedExisting;
        pgbson *upsertedObjectId;
    } lastErrorObject;
    pgbson *value;
} FindAndModifyResult;
PG_FUNCTION_INFO_V1(command_find_and_modify);
static FindAndModifySpec * ParseFindAndModifyMessage(pgbson *findAndModifyCommand);
static FindAndModifyResult * ProcessFindAndModifySpec(FindAndModifySpec *findAndModifySpec,
                                                     const char *databaseName);
Datum
command_find_and_modify(PG_FUNCTION_ARGS)
{
    pgbson *findAndModifyCommand = PG_GETARG_PGBSON(0);
    const char *databaseName = PG_GETARG_CSTRING(1);
    FindAndModifySpec *findAndModifySpec = ParseFindAndModifyMessage(findAndModifyCommand);
    FindAndModifyResult *findAndModifyResult = ProcessFindAndModifySpec(findAndModifySpec,
                                                                       databaseName);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    PgbsonWriterStartDocument(&writer, "lastErrorObject");
    PgbsonWriterAppendInt32(&writer, "n", findAndModifyResult->lastErrorObject.n);
    if (!findAndModifyResult->isUpdateCommand)
    {
        PgbsonWriterAppendBool(&writer, "updatedExisting",
                              findAndModifyResult->lastErrorObject.updatedExisting);
        if (findAndModifyResult->lastErrorObject.upsertedObjectId != NULL)
        {
            bson_iter_t upsertedIdIter;
            PgbsonInitIterator(findAndModifyResult->lastErrorObject.upsertedObjectId,
                              &upsertedIdIter);
            if (bson_iter_next(&upsertedIdIter))
            {
                const bson_value_t *upsertedIdValue = bson_iter_value(&upsertedIdIter);
                PgbsonWriterAppendValue(&writer, "upserted", upsertedIdValue);
            }
        }
    }
    PgbsonWriterEndDocument(&writer);
    if (findAndModifyResult->value != NULL)
    {
        PgbsonWriterAppendDocument(&writer, "value", findAndModifyResult->value);
    }
    else
    {
        PgbsonWriterAppendNull(&writer, "value");
    }
    PgbsonWriterAppendDouble(&writer, "ok", 1.0);
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
static FindAndModifySpec *
ParseFindAndModifyMessage(pgbson *findAndModifyCommand)
{
    FindAndModifySpec *findAndModifySpec = palloc0(sizeof(FindAndModifySpec));
    bson_iter_t findAndModifyIter;
    PgbsonInitIterator(findAndModifyCommand, &findAndModifyIter);
    while (bson_iter_next(&findAndModifyIter))
    {
        const char *key = bson_iter_key(&findAndModifyIter);
        const bson_value_t *value = bson_iter_value(&findAndModifyIter);
        if (strcmp(key, "findAndModify") == 0)
        {
            if (value->value_type != BSON_TYPE_UTF8)
            {
                ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                               errmsg("collection name must be a string")));
            }
            findAndModifySpec->collectionName = pstrdup(value->value.v_utf8.str);
        }
        else if (strcmp(key, "query") == 0)
        {
            findAndModifySpec->query = (bson_value_t *) value;
        }
        else if (strcmp(key, "sort") == 0)
        {
            findAndModifySpec->sort = (bson_value_t *) value;
        }
        else if (strcmp(key, "remove") == 0)
        {
            if (value->value_type == BSON_TYPE_BOOL)
            {
                findAndModifySpec->remove = value->value.v_bool;
            }
        }
        else if (strcmp(key, "update") == 0)
        {
            findAndModifySpec->update = (bson_value_t *) value;
        }
        else if (strcmp(key, "arrayFilters") == 0)
        {
            findAndModifySpec->arrayFilters = (bson_value_t *) value;
        }
        else if (strcmp(key, "new") == 0)
        {
            if (value->value_type == BSON_TYPE_BOOL)
            {
                findAndModifySpec->returnNewDocument = value->value.v_bool;
            }
        }
        else if (strcmp(key, "fields") == 0)
        {
            findAndModifySpec->returnFields = (bson_value_t *) value;
        }
        else if (strcmp(key, "upsert") == 0)
        {
            if (value->value_type == BSON_TYPE_BOOL)
            {
                findAndModifySpec->upsert = value->value.v_bool;
            }
        }
        else if (strcmp(key, "bypassDocumentValidation") == 0)
        {
            if (value->value_type == BSON_TYPE_BOOL)
            {
                findAndModifySpec->bypassDocumentValidation = value->value.v_bool;
            }
        }
    }
    if (findAndModifySpec->collectionName == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("BSON field 'findAndModify' is missing but a required field")));
    }
    if (findAndModifySpec->remove && findAndModifySpec->update != NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("Cannot specify both 'remove' and 'update' fields")));
    }
    if (!findAndModifySpec->remove && findAndModifySpec->update == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("Must specify either 'remove' or 'update' field")));
    }
    return findAndModifySpec;
}
```

## 第11页 共60页

### 文档更新操作 - update.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "funcapi.h"
#include "miscadmin.h"
#include "access/xact.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "utils/builtins.h"
#include "utils/typcache.h"
#include "io/bson_core.h"
#include "aggregation/bson_project.h"
#include "aggregation/bson_query.h"
#include "update/bson_update.h"
#include "commands/commands_common.h"
#include "commands/insert.h"
#include "commands/parse_error.h"
#include "commands/update.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "infrastructure/documentdb_plan_cache.h"
#include "query/query_operator.h"
#include "sharding/sharding.h"
#include "commands/retryable_writes.h"
#include "io/pgbsonsequence.h"
#include "utils/error_utils.h"
#include "utils/feature_counter.h"
#include "utils/query_utils.h"
#include "utils/version_utils.h"
#include "schema_validation/schema_validation.h"
#include "api_hooks.h"
typedef struct BatchUpdateSpec
{
    char *collectionName;
    List *updates;
    bool isOrdered;
    bool bypassDocumentValidation;
} BatchUpdateSpec;
typedef struct UpdateSpec
{
    bson_value_t *query;
    bson_value_t *update;
    bson_value_t *arrayFilters;
    bool upsert;
    bool multi;
    bson_value_t *collation;
    bson_value_t *hint;
} UpdateSpec;
typedef struct BatchUpdateResult
{
    double ok;
    uint64 nMatched;
    uint64 nModified;
    uint64 nUpserted;
    List *upserted;
    List *writeErrors;
    MemoryContext resultMemoryContext;
} BatchUpdateResult;
PG_FUNCTION_INFO_V1(command_update);
PG_FUNCTION_INFO_V1(command_update_bulk);
PG_FUNCTION_INFO_V1(command_update_one);
PG_FUNCTION_INFO_V1(command_update_worker);
static BatchUpdateSpec * BuildBatchUpdateSpec(bson_iter_t *updateCommandIter,
                                              pgbsonsequence *updateDocs);
static List * BuildUpdateSpecListFromSequence(pgbsonsequence *docSequence);
static BatchUpdateResult * ProcessBatchUpdate(BatchUpdateSpec *updateSpec,
                                             const char *databaseName,
                                             uint64 transactionId,
                                             bool isRetryableWrite);
static BatchUpdateResult * ProcessBatchUpdateCore(BatchUpdateSpec *updateSpec,
                                                 const char *databaseName,
                                                 uint64 transactionId,
                                                 bool isRetryableWrite,
                                                 bool isShardedCollection);
static BatchUpdateResult * ProcessBatchUpdateUnsharded(BatchUpdateSpec *updateSpec,
                                                      const char *databaseName);
static UpdateResult * ProcessUpdate(UpdateSpec *updateSpec,
                                   const char *databaseName,
                                   const char *collectionName);
static UpdateResult * UpdateAllMatchingDocuments(UpdateSpec *updateSpec,
                                                const char *databaseName,
                                                const char *collectionName,
                                                uint64 transactionId,
                                                bool isRetryableWrite,
                                                bool isShardedCollection,
                                                Oid shardOid,
                                                bson_value_t *shardKeyValue);
static UpdateResult * CallUpdateOne(UpdateSpec *updateSpec,
                                   const char *databaseName,
                                   const char *collectionName);
static UpdateResult * UpdateOneInternal(UpdateSpec *updateSpec,
                                       const char *databaseName,
                                       const char *collectionName);
static UpdateResult * UpdateOneInternalWithRetryRecord(UpdateSpec *updateSpec,
                                                      const char *databaseName,
                                                      const char *collectionName,
                                                      uint64 transactionId,
                                                      bool isRetryableWrite);
Datum
command_update(PG_FUNCTION_ARGS)
{
    pgbson *updateCommand = PG_GETARG_PGBSON(0);
    const char *databaseName = PG_GETARG_CSTRING(1);
    pgbsonsequence *updateDocs = PG_GETARG_PGBSONSEQUENCE(2);
    uint64 transactionId = PG_GETARG_INT64(3);
    bool isRetryableWrite = PG_GETARG_BOOL(4);
    bson_iter_t updateCommandIter;
    PgbsonInitIterator(updateCommand, &updateCommandIter);
    BatchUpdateSpec *updateSpec = BuildBatchUpdateSpec(&updateCommandIter, updateDocs);
    BatchUpdateResult *updateResult = ProcessBatchUpdate(updateSpec, databaseName,
                                                        transactionId, isRetryableWrite);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    PgbsonWriterAppendDouble(&writer, "ok", updateResult->ok);
    PgbsonWriterAppendInt64(&writer, "n", updateResult->nMatched);
    PgbsonWriterAppendInt64(&writer, "nModified", updateResult->nModified);
    if (updateResult->nUpserted > 0)
    {
        PgbsonWriterStartArray(&writer, "upserted");
        ListCell *upsertedCell;
        foreach(upsertedCell, updateResult->upserted)
        {
            pgbson *upsertedDoc = (pgbson *) lfirst(upsertedCell);
            PgbsonWriterAppendDocument(&writer, NULL, upsertedDoc);
        }
        PgbsonWriterEndArray(&writer);
    }
    if (updateResult->writeErrors != NIL)
    {
        PgbsonWriterStartArray(&writer, "writeErrors");
        ListCell *errorCell;
        foreach(errorCell, updateResult->writeErrors)
        {
            pgbson *errorDoc = (pgbson *) lfirst(errorCell);
            PgbsonWriterAppendDocument(&writer, NULL, errorDoc);
        }
        PgbsonWriterEndArray(&writer);
    }
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
static BatchUpdateResult *
ProcessBatchUpdate(BatchUpdateSpec *updateSpec, const char *databaseName,
                  uint64 transactionId, bool isRetryableWrite)
{
    MongoCollection *collection = GetMongoCollection(databaseName, updateSpec->collectionName);
    bool isShardedCollection = IsShardedCollection(collection);
    return ProcessBatchUpdateCore(updateSpec, databaseName, transactionId,
                                 isRetryableWrite, isShardedCollection);
}
static UpdateResult *
ProcessUpdate(UpdateSpec *updateSpec, const char *databaseName,
             const char *collectionName)
{
    MongoCollection *collection = GetMongoCollection(databaseName, collectionName);
    bool isShardedCollection = IsShardedCollection(collection);
    if (updateSpec->multi)
    {
        return UpdateAllMatchingDocuments(updateSpec, databaseName, collectionName,
                                        0, false, isShardedCollection, InvalidOid, NULL);
    }
    else
    {
        return CallUpdateOne(updateSpec, databaseName, collectionName);
    }
}
```

## 第12页 共60页

### 批量更新处理

```c
static BatchUpdateResult *
ProcessBatchUpdateCore(BatchUpdateSpec *updateSpec, const char *databaseName,
                      uint64 transactionId, bool isRetryableWrite,
                      bool isShardedCollection)
{
    BatchUpdateResult *batchResult = palloc0(sizeof(BatchUpdateResult));
    batchResult->ok = 1.0;
    batchResult->nMatched = 0;
    batchResult->nModified = 0;
    batchResult->nUpserted = 0;
    batchResult->upserted = NIL;
    batchResult->writeErrors = NIL;
    batchResult->resultMemoryContext = CurrentMemoryContext;
    ListCell *updateCell;
    int updateIndex = 0;
    foreach(updateCell, updateSpec->updates)
    {
        UpdateSpec *singleUpdateSpec = (UpdateSpec *) lfirst(updateCell);
        PG_TRY();
        {
            UpdateResult *updateResult = ProcessUpdate(singleUpdateSpec, databaseName,
                                                     updateSpec->collectionName);
            batchResult->nMatched += updateResult->nMatched;
            batchResult->nModified += updateResult->nModified;
            if (updateResult->upsertedId != NULL)
            {
                batchResult->nUpserted++;
                MemoryContext oldContext = MemoryContextSwitchTo(batchResult->resultMemoryContext);
                pgbson_writer upsertedWriter;
                PgbsonWriterInit(&upsertedWriter);
                PgbsonWriterAppendInt32(&upsertedWriter, "index", updateIndex);
                bson_iter_t upsertedIdIter;
                PgbsonInitIterator(updateResult->upsertedId, &upsertedIdIter);
                if (bson_iter_next(&upsertedIdIter))
                {
                    const bson_value_t *upsertedIdValue = bson_iter_value(&upsertedIdIter);
                    PgbsonWriterAppendValue(&upsertedWriter, "_id", upsertedIdValue);
                }
                batchResult->upserted = lappend(batchResult->upserted,
                                              PgbsonWriterGetPgbson(&upsertedWriter));
                MemoryContextSwitchTo(oldContext);
            }
        }
        PG_CATCH();
        {
            ErrorData *errorData = CopyErrorData();
            FlushErrorState();
            MemoryContext oldContext = MemoryContextSwitchTo(batchResult->resultMemoryContext);
            pgbson_writer errorWriter;
            PgbsonWriterInit(&errorWriter);
            PgbsonWriterAppendInt32(&errorWriter, "index", updateIndex);
            PgbsonWriterAppendInt32(&errorWriter, "code", errorData->sqlerrcode);
            PgbsonWriterAppendUtf8(&errorWriter, "errmsg", errorData->message);
            batchResult->writeErrors = lappend(batchResult->writeErrors,
                                             PgbsonWriterGetPgbson(&errorWriter));
            MemoryContextSwitchTo(oldContext);
            FreeErrorData(errorData);
            if (updateSpec->isOrdered)
            {
                break;
            }
        }
        PG_END_TRY();
        updateIndex++;
    }
    return batchResult;
}
```

## 第13页 共60页

### 集合元数据管理 - collection.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "access/xact.h"
#include "catalog/pg_attribute.h"
#include "commands/extension.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "nodes/makefuncs.h"
#include "nodes/pg_list.h"
#include "parser/parse_func.h"
#include "storage/lmgr.h"
#include "funcapi.h"
#include "utils/builtins.h"
#include "utils/catcache.h"
#include "utils/guc.h"
#include "utils/inval.h"
#include "utils/lsyscache.h"
#include "utils/memutils.h"
#include "utils/syscache.h"
#include "utils/version_utils.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "utils/documentdb_errors.h"
#include "metadata/relation_utils.h"
#include "utils/query_utils.h"
#include "utils/guc_utils.h"
#include "metadata/metadata_guc.h"
#include "api_hooks.h"
#include "commands/parse_error.h"
#include "utils/feature_counter.h"
#define CREATE_COLLECTION_FUNC_NARGS 2
typedef struct NameToCollectionCacheEntry
{
    MongoCollectionName name;
    MongoCollection collection;
    bool isValid;
} NameToCollectionCacheEntry;
typedef struct RelationIdToCollectionCacheEntry
{
    Oid relationId;
    MongoCollection collection;
    bool isValid;
} RelationIdToCollectionCacheEntry;
static const char CharactersNotAllowedInDatabaseNames[7] = {
    '/', '\\', '.', ' ', '"', '$', '\0'
};
static const int CharactersNotAllowedInDatabaseNamesLength =
    sizeof(CharactersNotAllowedInDatabaseNames);
static const char CharactersNotAllowedInCollectionNames[2] = { '$', '\0' };
static const int CharactersNotAllowedInCollectionNamesLength =
    sizeof(CharactersNotAllowedInCollectionNames);
static const char *ValidSystemCollectionNames[5] = {
    "system.users", "system.js", "system.views", "system.profile", "system.dbSentinel"
};
static const int ValidSystemCollectionNamesLength = 5;
static const char *NonWritableSystemCollectionNames[4] = {
    "system.users", "system.js", "system.views", "system.profile"
};
static const int NonWritableSystemCollectionNamesLength = 4;
static HTAB *NameToCollectionHash = NULL;
static HTAB *RelationIdToCollectionHash = NULL;
static MemoryContext CollectionCacheMemoryContext = NULL;
static MongoCollection * GetMongoCollectionFromCatalogById(uint64 collectionId);
static MongoCollection * GetMongoCollectionFromCatalogByNameDatum(Datum databaseNameDatum,
                                                                  Datum collectionNameDatum);
static Oid GetRelationIdForCollectionTableName(const char *tableName);
static MongoCollection * GetMongoCollectionByNameDatumCore(Datum databaseNameDatum,
                                                          Datum collectionNameDatum,
                                                          bool missingOk);
void
InitializeCollectionsHash(void)
{
    HASHCTL info;
    MemSet(&info, 0, sizeof(info));
    info.keysize = sizeof(MongoCollectionName);
    info.entrysize = sizeof(NameToCollectionCacheEntry);
    info.hash = tag_hash;
    info.hcxt = CollectionCacheMemoryContext;
    NameToCollectionHash = hash_create("NameToCollectionHash",
                                      32, &info,
                                      HASH_ELEM | HASH_FUNCTION | HASH_CONTEXT);
    MemSet(&info, 0, sizeof(info));
    info.keysize = sizeof(Oid);
    info.entrysize = sizeof(RelationIdToCollectionCacheEntry);
    info.hash = oid_hash;
    info.hcxt = CollectionCacheMemoryContext;
    RelationIdToCollectionHash = hash_create("RelationIdToCollectionHash",
                                            32, &info,
                                            HASH_ELEM | HASH_FUNCTION | HASH_CONTEXT);
    CacheRegisterSyscacheCallback(RELOID, InvalidateCollectionByRelationId, (Datum) 0);
}
void
ResetCollectionsCache(void)
{
    if (NameToCollectionHash != NULL)
    {
        hash_destroy(NameToCollectionHash);
        NameToCollectionHash = NULL;
    }
    if (RelationIdToCollectionHash != NULL)
    {
        hash_destroy(RelationIdToCollectionHash);
        RelationIdToCollectionHash = NULL;
    }
}
static void
InvalidateCollectionByRelationId(Datum argument, Oid relationId)
{
    HASH_SEQ_STATUS status;
    RelationIdToCollectionCacheEntry *entry;
    if (RelationIdToCollectionHash == NULL)
    {
        return;
    }
    hash_seq_init(&status, RelationIdToCollectionHash);
    while ((entry = (RelationIdToCollectionCacheEntry *) hash_seq_search(&status)) != NULL)
    {
        if (entry->relationId == relationId)
        {
            entry->isValid = false;
        }
    }
    hash_seq_init(&status, NameToCollectionHash);
    NameToCollectionCacheEntry *nameEntry;
    while ((nameEntry = (NameToCollectionCacheEntry *) hash_seq_search(&status)) != NULL)
    {
        if (nameEntry->collection.relationId == relationId)
        {
            nameEntry->isValid = false;
        }
    }
}
MongoCollection *
GetMongoCollection(const char *databaseName, const char *collectionName)
{
    Datum databaseNameDatum = CStringGetTextDatum(databaseName);
    Datum collectionNameDatum = CStringGetTextDatum(collectionName);
    return GetMongoCollectionByNameDatum(databaseNameDatum, collectionNameDatum);
}
MongoCollection *
GetMongoCollectionByNameDatum(Datum databaseNameDatum, Datum collectionNameDatum)
{
    return GetMongoCollectionByNameDatumCore(databaseNameDatum, collectionNameDatum, false);
}
```

## 第14页 共60页

### 查询操作符处理 - query_operator.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <catalog/namespace.h>
#include <catalog/pg_collation.h>
#include <catalog/pg_operator.h>
#include <executor/executor.h>
#include <optimizer/optimizer.h>
#include <nodes/makefuncs.h>
#include <nodes/nodes.h>
#include <nodes/nodeFuncs.h>
#include <utils/builtins.h>
#include <utils/typcache.h>
#include <utils/lsyscache.h>
#include <utils/syscache.h>
#include <utils/timestamp.h>
#include <utils/array.h>
#include <parser/parse_coerce.h>
#include <parser/parsetree.h>
#include <parser/parse_clause.h>
#include <catalog/pg_type.h>
#include <funcapi.h>
#include <lib/stringinfo.h>
#include <metadata/metadata_cache.h>
#include <math.h>
#include <nodes/supportnodes.h>
#include "io/bson_core.h"
#include "query/bson_compare.h"
#include "aggregation/bson_query.h"
#include "types/decimal128.h"
#include "utils/documentdb_errors.h"
#include "commands/defrem.h"
#include "geospatial/bson_geospatial_common.h"
#include "geospatial/bson_geospatial_geonear.h"
#include "geospatial/bson_geospatial_shape_operators.h"
#include "metadata/collection.h"
#include "planner/documentdb_planner.h"
#include "query/query_operator.h"
#include "sharding/sharding.h"
#include "utils/rel.h"
#include "opclass/bson_text_gin.h"
#include "utils/feature_counter.h"
#include "vector/vector_common.h"
#include "vector/vector_utilities.h"
#include "types/pcre_regex.h"
#include "query/bson_dollar_operators.h"
#include "commands/commands_common.h"
#include "utils/version_utils.h"
#include "collation/collation.h"
#include "jsonschema/bson_json_schema_tree.h"
typedef struct ReplaceBsonQueryOperatorsContext
{
    Query *currentQuery;
    ParamListInfo boundParams;
    List *sortClauses;
    List *targetEntries;
} ReplaceBsonQueryOperatorsContext;
typedef struct IdFilterWalkerContext
{
    List *idQuals;
    bool foundIdFilter;
    bool foundNonIdFilter;
    bool foundComplexIdFilter;
} IdFilterWalkerContext;
static Node * ReplaceBsonQueryOperatorsMutator(Node *node, void *context);
static List * ExpandBsonQueryOperator(Expr *leftExpr, Expr *rightExpr,
                                     ReplaceBsonQueryOperatorsContext *context);
static BoolExpr * CreateBoolExprFromLogicalExpression(const char *operatorName,
                                                     const bson_value_t *operatorValue,
                                                     Expr *documentExpr,
                                                     ReplaceBsonQueryOperatorsContext *context);
static List * CreateQualsFromLogicalExpressionArrayIterator(bson_iter_t *arrayIterator,
                                                           Expr *documentExpr,
                                                           ReplaceBsonQueryOperatorsContext *context);
static OpExpr * CreateOpExprFromComparisonExpression(const char *operatorName,
                                                    const bson_value_t *operatorValue,
                                                    Expr *documentExpr,
                                                    ReplaceBsonQueryOperatorsContext *context);
static OpExpr * CreateOpExprFromOperatorDocIterator(bson_iter_t *operatorDocIterator,
                                                   Expr *documentExpr,
                                                   ReplaceBsonQueryOperatorsContext *context);
static OpExpr * CreateOpExprFromOperatorDocIteratorCore(bson_iter_t *operatorDocIterator,
                                                       Expr *documentExpr,
                                                       ReplaceBsonQueryOperatorsContext *context,
                                                       bool isNegated);
static FuncExpr * CreateFuncExprForQueryOperator(const char *operatorName,
                                                const bson_value_t *operatorValue,
                                                Expr *documentExpr,
                                                ReplaceBsonQueryOperatorsContext *context);
static Const * CreateConstFromBsonValue(const bson_value_t *value);
static Expr * CreateExprForDollarAll(const bson_value_t *operatorValue,
                                    Expr *documentExpr,
                                    ReplaceBsonQueryOperatorsContext *context);
static List * ExpandExprForDollarAll(const bson_value_t *operatorValue,
                                    Expr *documentExpr,
                                    ReplaceBsonQueryOperatorsContext *context);
static MongoCollection * GetCollectionReferencedByDocumentVar(Expr *documentExpr,
                                                             ReplaceBsonQueryOperatorsContext *context);
static MongoCollection * GetCollectionForRTE(RangeTblEntry *rte);
static Expr * CreateExprForDollarRegex(const bson_value_t *operatorValue,
                                      Expr *documentExpr,
                                      ReplaceBsonQueryOperatorsContext *context);
static FuncExpr * CreateFuncExprForRegexOperator(const bson_value_t *regexValue,
                                                const bson_value_t *optionsValue,
                                                Expr *documentExpr,
                                                ReplaceBsonQueryOperatorsContext *context);
static Expr * CreateExprForDollarMod(const bson_value_t *operatorValue,
                                    Expr *documentExpr,
                                    ReplaceBsonQueryOperatorsContext *context);
static Expr * CreateExprForBitwiseQueryOperators(const char *operatorName,
                                                const bson_value_t *operatorValue,
                                                Expr *documentExpr,
                                                ReplaceBsonQueryOperatorsContext *context);
static void SortAndWriteInt32BsonTypeArray(pgbson_writer *writer, const char *key,
                                          int32 *typeArray, int arrayLength);
static List * CreateQualsFromQueryDocIteratorInternal(bson_iter_t *queryDocIterator,
                                                     Expr *documentExpr,
                                                     ReplaceBsonQueryOperatorsContext *context);
static Expr * CreateQualForBsonValueExpressionCore(const char *path,
                                                   const bson_value_t *value,
                                                   Expr *documentExpr,
                                                   ReplaceBsonQueryOperatorsContext *context);
static bool TryProcessOrIntoDollarIn(List *orQualsList, List **processedQuals);
static bool TryOptimizeDollarOrExpr(List *orQualsList);
static OpExpr * ParseBsonValueForNearAndCreateOpExpr(const bson_value_t *operatorValue,
                                                    Expr *documentExpr,
                                                    ReplaceBsonQueryOperatorsContext *context);
static Expr * WithIndexSupportExpression(Expr *expression);
bool
IsDoubleAFixedInteger(double value)
{
    return value == floor(value) && value >= INT32_MIN && value <= INT32_MAX;
}
Datum
bson_query_match(PG_FUNCTION_ARGS)
{
    pgbson *document = PG_GETARG_PGBSON(0);
    pgbson *query = PG_GETARG_PGBSON(1);
    if (document == NULL || query == NULL)
    {
        PG_RETURN_BOOL(false);
    }
    bson_iter_t queryIterator;
    PgbsonInitIterator(query, &queryIterator);
    if (!bson_iter_next(&queryIterator))
    {
        PG_RETURN_BOOL(true);
    }
    bson_iter_t documentIterator;
    PgbsonInitIterator(document, &documentIterator);
    bool result = true;
    do
    {
        const char *queryKey = bson_iter_key(&queryIterator);
        const bson_value_t *queryValue = bson_iter_value(&queryIterator);
        bool foundMatch = false;
        PgbsonInitIterator(document, &documentIterator);
        while (bson_iter_next(&documentIterator))
        {
            const char *documentKey = bson_iter_key(&documentIterator);
            if (strcmp(queryKey, documentKey) == 0)
            {
                const bson_value_t *documentValue = bson_iter_value(&documentIterator);
                if (BsonValueEquals(queryValue, documentValue))
                {
                    foundMatch = true;
                    break;
                }
            }
        }
        if (!foundMatch)
        {
            result = false;
            break;
        }
    } while (bson_iter_next(&queryIterator));
    PG_RETURN_BOOL(result);
}
static List *
ExpandBsonQueryOperator(Expr *leftExpr, Expr *rightExpr,
                       ReplaceBsonQueryOperatorsContext *context)
{
    if (!IsA(rightExpr, Const))
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
                       errmsg("Query operator right expression must be a constant")));
    }
    Const *queryConst = (Const *) rightExpr;
    if (queryConst->constisnull)
    {
        return NIL;
    }
    pgbson *queryDocument = DatumGetPgBson(queryConst->constvalue);
    bson_iter_t queryDocIterator;
    PgbsonInitIterator(queryDocument, &queryDocIterator);
    return CreateQualsFromQueryDocIteratorInternal(&queryDocIterator, leftExpr, context);
}
```

## 第15页 共60页

### BSON查询匹配与操作符展开

```c
static List *
CreateQualsFromQueryDocIteratorInternal(bson_iter_t *queryDocIterator,
                                       Expr *documentExpr,
                                       ReplaceBsonQueryOperatorsContext *context)
{
    List *qualsList = NIL;
    while (bson_iter_next(queryDocIterator))
    {
        const char *path = bson_iter_key(queryDocIterator);
        const bson_value_t *value = bson_iter_value(queryDocIterator);
        if (path[0] == '$')
        {
            if (strcmp(path, "$and") == 0)
            {
                BoolExpr *andExpr = CreateBoolExprFromLogicalExpression(path, value,
                                                                       documentExpr, context);
                qualsList = lappend(qualsList, andExpr);
            }
            else if (strcmp(path, "$or") == 0)
            {
                BoolExpr *orExpr = CreateBoolExprFromLogicalExpression(path, value,
                                                                      documentExpr, context);
                qualsList = lappend(qualsList, orExpr);
            }
            else if (strcmp(path, "$nor") == 0)
            {
                BoolExpr *norExpr = CreateBoolExprFromLogicalExpression(path, value,
                                                                       documentExpr, context);
                qualsList = lappend(qualsList, norExpr);
            }
            else
            {
                ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                               errmsg("unknown top level operator: %s", path)));
            }
        }
        else
        {
            Expr *pathExpr = CreateQualForBsonValueExpressionCore(path, value,
                                                                 documentExpr, context);
            qualsList = lappend(qualsList, pathExpr);
        }
    }
    return qualsList;
}
static BoolExpr *
CreateBoolExprFromLogicalExpression(const char *operatorName,
                                   const bson_value_t *operatorValue,
                                   Expr *documentExpr,
                                   ReplaceBsonQueryOperatorsContext *context)
{
    if (operatorValue->value_type != BSON_TYPE_ARRAY)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                       errmsg("%s must be an array", operatorName)));
    }
    bson_iter_t arrayIterator;
    BsonValueInitIterator(operatorValue, &arrayIterator);
    List *qualsList = CreateQualsFromLogicalExpressionArrayIterator(&arrayIterator,
                                                                   documentExpr, context);
    if (qualsList == NIL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                       errmsg("%s must be a nonempty array", operatorName)));
    }
    BoolExprType boolType;
    if (strcmp(operatorName, "$and") == 0)
    {
        boolType = AND_EXPR;
    }
    else if (strcmp(operatorName, "$or") == 0)
    {
        boolType = OR_EXPR;
    }
    else if (strcmp(operatorName, "$nor") == 0)
    {
        boolType = NOT_EXPR;
        BoolExpr *orExpr = makeBoolExpr(OR_EXPR, qualsList, -1);
        qualsList = list_make1(orExpr);
        boolType = NOT_EXPR;
    }
    else
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
                       errmsg("Unknown logical operator: %s", operatorName)));
    }
    return makeBoolExpr(boolType, qualsList, -1);
}
```

## 第16页 共60页

### 索引元数据管理 - index.c

```c
#include <postgres.h>
#include <catalog/namespace.h>
#include <commands/sequence.h>
#include <executor/spi.h>
#include <utils/array.h>
#include <utils/builtins.h>
#include <utils/expandedrecord.h>
#include <utils/lsyscache.h>
#include <utils/syscache.h>
#include <nodes/makefuncs.h>
#include <catalog/namespace.h>
#include <miscadmin.h>
#include "api_hooks.h"
#include "io/bson_core.h"
#include "query/bson_compare.h"
#include "commands/create_indexes.h"
#include "metadata/index.h"
#include "metadata/metadata_cache.h"
#include "query/query_operator.h"
#include "utils/list_utils.h"
#include "metadata/relation_utils.h"
#include "utils/guc_utils.h"
#include "utils/query_utils.h"
#include "utils/documentdb_errors.h"
#include "metadata/metadata_guc.h"
#include "utils/version_utils.h"
#include "metadata/metadata_cache.h"
#include "utils/hashset_utils.h"
extern int MaxNumActiveUsersIndexBuilds;
extern int IndexBuildScheduleInSec;
static List * WriteIndexKeyForGetIndexes(pgbson_writer *writer, pgbson *keyDocument);
static pgbson * SerializeIndexSpec(const IndexSpec *spec, bool isGetIndexes,
                                   const char *namespaceName);
static IndexOptionsEquivalency IndexKeyDocumentEquivalent(pgbson *leftKey,
                                                          pgbson *rightKey);
static void DeleteCollectionIndexRecordCore(uint64 collectionId, int *indexId);
static ArrayType * ConvertUint64ListToArray(List *collectionIdArray);
static IndexOptionsEquivalency GetOptionsEquivalencyFromIndexOptions(
    HTAB *bsonElementHash,
    pgbson *leftIndexSpec,
    pgbson *rightIndexSpec);
PG_FUNCTION_INFO_V1(command_record_id_index);
PG_FUNCTION_INFO_V1(index_spec_options_are_equivalent);
PG_FUNCTION_INFO_V1(command_get_next_collection_index_id);
PG_FUNCTION_INFO_V1(index_spec_as_bson);
PG_FUNCTION_INFO_V1(get_index_spec_as_current_op_command);
Datum
command_record_id_index(PG_FUNCTION_ARGS)
{
    if (PG_ARGISNULL(0))
    {
        ereport(ERROR, (errmsg("collectionId cannot be NULL")));
    }
    uint64 collectionId = DatumGetUInt64(PG_GETARG_DATUM(0));
    IndexSpec idIndexSpec = MakeIndexSpecForBuiltinIdIndex();
    bool indexIsValid = true;
    RecordCollectionIndex(collectionId, &idIndexSpec, indexIsValid);
    PG_RETURN_VOID();
}
Datum
index_spec_options_are_equivalent(PG_FUNCTION_ARGS)
{
    if (PG_ARGISNULL(0) || PG_ARGISNULL(1))
    {
        PG_RETURN_BOOL(false);
    }
    pgbson *leftIndexSpec = PG_GETARG_PGBSON(0);
    pgbson *rightIndexSpec = PG_GETARG_PGBSON(1);
    IndexOptionsEquivalency equivalency = IndexSpecOptionsAreEquivalent(leftIndexSpec,
                                                                        rightIndexSpec);
    PG_RETURN_BOOL(equivalency == IndexOptionsEquivalent);
}
Datum
index_spec_as_bson(PG_FUNCTION_ARGS)
{
    if (PG_ARGISNULL(0))
    {
        ereport(ERROR, (errmsg("indexSpec cannot be NULL")));
    }
    IndexSpec *indexSpec = (IndexSpec *) PG_GETARG_POINTER(0);
    bool isGetIndexes = PG_GETARG_BOOL(1);
    const char *namespaceName = PG_ARGISNULL(2) ? NULL : PG_GETARG_CSTRING(2);
    pgbson *result = SerializeIndexSpec(indexSpec, isGetIndexes, namespaceName);
    PG_RETURN_POINTER(result);
}
```

## 第17页 共60页

### 索引创建命令处理 - create_indexes.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <funcapi.h>
#include <math.h>
#include <miscadmin.h>
#include <access/xact.h>
#include <catalog/namespace.h>
#include <executor/executor.h>
#include <executor/spi.h>
#include <lib/stringinfo.h>
#include <nodes/makefuncs.h>
#include <nodes/nodeFuncs.h>
#include <optimizer/optimizer.h>
#include <storage/lmgr.h>
#include <storage/lockdefs.h>
#include <storage/proc.h>
#include <tcop/pquery.h>
#include <tcop/utility.h>
#include <utils/builtins.h>
#include <utils/lsyscache.h>
#include <utils/ruleutils.h>
#include <utils/snapmgr.h>
#include <utils/syscache.h>
#include <catalog/index.h>
#include "api_hooks.h"
#include "io/bson_core.h"
#include "aggregation/bson_projection_tree.h"
#include "commands/commands_common.h"
#include "commands/create_indexes.h"
#include "commands/diagnostic_commands_common.h"
#include "commands/drop_indexes.h"
#include "commands/lock_tags.h"
#include "commands/parse_error.h"
#include "geospatial/bson_geospatial_common.h"
#include "geospatial/bson_geospatial_geonear.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "planner/mongo_query_operator.h"
#include "query/query_operator.h"
#include "utils/error_utils.h"
#include "utils/guc_utils.h"
#include "utils/list_utils.h"
#include "utils/documentdb_errors.h"
#include "utils/query_utils.h"
#include "utils/feature_counter.h"
#include "utils/index_utils.h"
#include "utils/version_utils.h"
#include "vector/vector_common.h"
#include "vector/vector_utilities.h"
#include "index_am/index_am_utils.h"
#define MAX_INDEX_OPTIONS_LENGTH 1500
typedef struct
{
    bool ok;
    char *errmsg;
    int errcode;
} TryCreateIndexesResult;
typedef struct
{
    bool ok;
    char *errmsg;
    int errcode;
    IndexDetails *indexCurrentlyBuilding;
} TryReIndexesResult;
typedef struct
{
    pgbson *indexSpec;
    char *indexName;
    bool indexIsBuilding;
    bool indexIsValid;
} ReIndexResultData;
static TryCreateIndexesResult TryCreateCollectionIndexes(uint64 collectionId,
                                                        List *indexSpecList,
                                                        bool isConcurrent,
                                                        bool isTemp);
static TryCreateIndexesResult TryCreateInvalidCollectionIndexes(uint64 collectionId,
                                                               List *indexSpecList);
static TryReIndexesResult TryReIndexCollectionIndexesConcurrently(uint64 collectionId,
                                                                 List *indexSpecList,
                                                                 List *indexNameList,
                                                                 bool dropTarget,
                                                                 bool isBackground);
static void TryDropFailedCollectionIndexesAfterReIndex(uint64 collectionId,
                                                      List *indexSpecList);
static void CreatePostgresIndex(uint64 collectionId, IndexSpec *indexSpec,
                               bool isConcurrent);
static void ReIndexPostgresIndex(uint64 collectionId, IndexSpec *indexSpec);
bool
IsCallCreateIndexesStmt(PlannedStmt *plannedStmt)
{
    if (plannedStmt->commandType != CMD_UTILITY)
    {
        return false;
    }
    Node *parsetree = plannedStmt->utilityStmt;
    if (!IsA(parsetree, CallStmt))
    {
        return false;
    }
    CallStmt *callStmt = (CallStmt *) parsetree;
    return IsCreateIndexesFuncCall(callStmt->funcexpr);
}
bool
IsCallReIndexStmt(PlannedStmt *plannedStmt)
{
    if (plannedStmt->commandType != CMD_UTILITY)
    {
        return false;
    }
    Node *parsetree = plannedStmt->utilityStmt;
    if (!IsA(parsetree, CallStmt))
    {
        return false;
    }
    CallStmt *callStmt = (CallStmt *) parsetree;
    return IsReIndexFuncCall(callStmt->funcexpr);
}
int
ComputeIndexTermLimit(IndexSpec *indexSpec)
{
    if (IsTextIndex(indexSpec))
    {
        return _RUM_TERM_SIZE_LIMIT;
    }
    else if (IsSinglePathIndex(indexSpec))
    {
        return SINGLE_PATH_INDEX_TERM_SIZE_LIMIT;
    }
    else
    {
        return COMPOUND_INDEX_TERM_SIZE_LIMIT;
    }
}
bool
IsUniqueIndex(IndexSpec *indexSpec)
{
    return indexSpec->isUnique;
}
bool
IsWildCardIndex(IndexSpec *indexSpec)
{
    return indexSpec->isWildcardProjection;
}
bool
IsSinglePathIndex(IndexSpec *indexSpec)
{
    return !IsCompositePathIndex(indexSpec);
}
bool
IsCompositePathIndex(IndexSpec *indexSpec)
{
    bson_iter_t keyIterator;
    PgbsonInitIterator(indexSpec->keyDocument, &keyIterator);
    int keyCount = 0;
    while (bson_iter_next(&keyIterator))
    {
        keyCount++;
        if (keyCount > 1)
        {
            return true;
        }
    }
    return false;
}
bool
IsTextIndex(IndexSpec *indexSpec)
{
    bson_iter_t keyIterator;
    PgbsonInitIterator(indexSpec->keyDocument, &keyIterator);
    while (bson_iter_next(&keyIterator))
    {
        const bson_value_t *value = bson_iter_value(&keyIterator);
        if (value->value_type == BSON_TYPE_UTF8 &&
            strcmp(value->value.v_utf8.str, "text") == 0)
        {
            return true;
        }
    }
    return false;
}
bool
IsHashIndex(IndexSpec *indexSpec)
{
    bson_iter_t keyIterator;
    PgbsonInitIterator(indexSpec->keyDocument, &keyIterator);
    while (bson_iter_next(&keyIterator))
    {
        const bson_value_t *value = bson_iter_value(&keyIterator);
        if (value->value_type == BSON_TYPE_UTF8 &&
            strcmp(value->value.v_utf8.str, "hashed") == 0)
        {
            return true;
        }
    }
    return false;
}
```

## 第18页 共60页

### 向量搜索功能 - vector_utilities.c

```c
#include <postgres.h>
#include <catalog/pg_operator.h>
#include <catalog/pg_type.h>
#include <nodes/makefuncs.h>
#include <utils/array.h>
#include <utils/builtins.h>
#include <utils/rel.h>
#include <utils/syscache.h>
#include <commands/defrem.h>
#include <catalog/pg_collation.h>
#include <utils/lsyscache.h>
#include "api_hooks.h"
#include "io/bson_core.h"
#include "utils/documentdb_errors.h"
#include "metadata/metadata_cache.h"
#include "vector/bson_extract_vector.h"
#include "vector/vector_common.h"
#include "vector/vector_configs.h"
#include "vector/vector_planner.h"
#include "vector/vector_utilities.h"
#include "vector/vector_spec.h"
#include "utils/error_utils.h"
static Expr * GenerateVectorExractionExprFromQueryWithCast(Node *vectorQuerySpecNode,
                                                           FuncExpr *vectorCastFunc);
static VectorIndexDistanceMetric GetDistanceMetricFromOpId(Oid similaritySearchOpId);
static VectorIndexDistanceMetric GetDistanceMetricFromOpName(const
                                                             char *similaritySearchOpName);
static bool IsHalfVectorCastFunctionCore(FuncExpr *vectorCastFunc,
                                         bool logWarning);
double
EvaluateMetaSearchScore(pgbson *document)
{
    const char *metaScorePathName =
        VECTOR_METADATA_FIELD_NAME "." VECTOR_METADATA_SCORE_FIELD_NAME;
    bson_iter_t documentIterator;
    if (PgbsonInitIteratorAtPath(document, metaScorePathName, &documentIterator))
    {
        return BsonValueAsDouble(bson_iter_value(&documentIterator));
    }
    else
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_LOCATION40218),
                        errmsg(
                            "query requires search score metadata, but it is not available")));
    }
}
void
CalculateDefaultSearchParameters(uint64 numRows, VectorIndexKind indexKind,
                                VectorIndexSpec *indexSpec, int *nProbes, int *efSearch)
{
    if (indexKind == VectorIndexKind_IVFFlat)
    {
        int nLists = indexSpec->ivfFlatSpec.nLists;
        if (numRows < 10000)
        {
            *nProbes = nLists;
        }
        else if (numRows < 1000000)
        {
            *nProbes = (int) (numRows / 1000);
        }
        else
        {
            *nProbes = (int) sqrt(numRows);
        }
        *nProbes = Min(*nProbes, nLists);
        *nProbes = Max(*nProbes, 1);
    }
    else if (indexKind == VectorIndexKind_HNSW)
    {
        int efConstruction = indexSpec->hnswSpec.efConstruction;
        if (numRows < 10000)
        {
            *efSearch = efConstruction;
        }
        else if (numRows < 1000000)
        {
            *efSearch = (int) (numRows / 1000);
        }
        else
        {
            *efSearch = (int) sqrt(numRows);
        }
        *efSearch = Max(*efSearch, 1);
    }
}
```

## 第19页 共60页

### 地理空间处理 - bson_geospatial_common.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "math.h"
#include "utils/builtins.h"
#include "utils/documentdb_errors.h"
#include "geospatial/bson_geojson_utils.h"
#include "geospatial/bson_geospatial_common.h"
#include "geospatial/bson_geospatial_private.h"
#include "utils/list_utils.h"
#include "io/bson_traversal.h"
#define IsIndexValidation(s) (s->validationLevel == GeospatialValidationLevel_Index)
#define IsBloomValidation(s) (s->validationLevel == GeospatialValidationLevel_BloomFilter)
#define IsRuntimeValidation(s) (s->validationLevel == GeospatialValidationLevel_Runtime)
#define IsIndexMultiKey(s) (IsIndexValidation(s) && s->isMultiKeyContext == true)
typedef enum PointProcessType
{
    PointProcessType_Invalid = 0,
    PointProcessType_Empty,
    PointProcessType_Valid,
} PointProcessType;
static bool LegacyPointVisitTopLevelField(pgbsonelement *element, const
                                          StringView *filterPath,
                                          void *state);
static bool GeographyVisitTopLevelField(pgbsonelement *element, const
                                        StringView *filterPath,
                                        void *state);
static bool GeographyValidateTopLevelField(pgbsonelement *element, const
                                           StringView *filterPath,
                                           void *state);
static bool ContinueProcessIntermediateArray(void *state, const
                                             bson_value_t *value);
static bool BsonValueAddLegacyPointDatum(const bson_value_t *value,
                                         ProcessCommonGeospatialState *state,
                                         bool *isNull);
static bool BsonValueParseAsLegacyPoint2d(const bson_value_t *value,
                                          ProcessCommonGeospatialState *state);
static const char * _2dsphereIndexErrorPrefix(const pgbson *document);
static const char * _2dsphereIndexErrorHintPrefix(const pgbson *document);
static const char * _2dIndexNoPrefix(const pgbson *document);
static Datum BsonExtractGeospatialInternal(const pgbson *document,
                                           const StringView *pathView,
                                           GeospatialType type,
                                           GeospatialValidationLevel level,
                                           WKBGeometryType collectType,
                                           GeospatialErrorContext *errCtxt);
static void SetQueryMatcherResult(ProcessCommonGeospatialState *state);
static const TraverseBsonExecutionFuncs ProcessLegacyCoordinates = {
    .ContinueProcessIntermediateArray = ContinueProcessIntermediateArray,
    .SetTraverseResult = NULL,
    .VisitArrayField = NULL,
    .VisitTopLevelField = LegacyPointVisitTopLevelField,
    .SetIntermediateArrayIndex = NULL,
    .HandleIntermediateArrayPathNotFound = NULL,
    .SetIntermediateArrayStartEnd = NULL,
};
static const TraverseBsonExecutionFuncs ProcessGeographyCoordinates = {
    .ContinueProcessIntermediateArray = ContinueProcessIntermediateArray,
    .SetTraverseResult = NULL,
    .VisitArrayField = NULL,
    .VisitTopLevelField = GeographyVisitTopLevelField,
    .SetIntermediateArrayIndex = NULL,
    .HandleIntermediateArrayPathNotFound = NULL,
    .SetIntermediateArrayStartEnd = NULL,
};
static const TraverseBsonExecutionFuncs ValidateGeographyCoordinates = {
    .ContinueProcessIntermediateArray = ContinueProcessIntermediateArray,
    .SetTraverseResult = NULL,
    .VisitArrayField = NULL,
    .VisitTopLevelField = GeographyValidateTopLevelField,
    .SetIntermediateArrayIndex = NULL,
    .HandleIntermediateArrayPathNotFound = NULL,
    .SetIntermediateArrayStartEnd = NULL,
};
void
UpdateStateAndRunMatcherIfValidPointFound(ProcessCommonGeospatialState *state)
{
    if (state->isValidPoint)
    {
        SetQueryMatcherResult(state);
        state->isValidPoint = false;
        state->pointProcessType[0] = PointProcessType_Invalid;
        state->pointProcessType[1] = PointProcessType_Invalid;
    }
}
Datum
BsonIterGetLegacyGeometryPoints(PG_FUNCTION_ARGS)
{
    pgbson *document = PG_GETARG_PGBSON(0);
    text *pathText = PG_GETARG_TEXT_P(1);
    StringView pathView = CreateStringViewFromText(pathText);
    ProcessCommonGeospatialState state = { 0 };
    state.validationLevel = GeospatialValidationLevel_Index;
    TraverseBsonByPath(document, &pathView, &ProcessLegacyCoordinates, &state);
    PG_RETURN_ARRAYTYPE_P(state.resultArray);
}
Datum
BsonIterGetGeographies(PG_FUNCTION_ARGS)
{
    pgbson *document = PG_GETARG_PGBSON(0);
    text *pathText = PG_GETARG_TEXT_P(1);
    StringView pathView = CreateStringViewFromText(pathText);
    ProcessCommonGeospatialState state = { 0 };
    state.validationLevel = GeospatialValidationLevel_Index;
    TraverseBsonByPath(document, &pathView, &ProcessGeographyCoordinates, &state);
    PG_RETURN_ARRAYTYPE_P(state.resultArray);
}
Datum
BsonIterValidateGeographies(PG_FUNCTION_ARGS)
{
    pgbson *document = PG_GETARG_PGBSON(0);
    text *pathText = PG_GETARG_TEXT_P(1);
    StringView pathView = CreateStringViewFromText(pathText);
    ProcessCommonGeospatialState state = { 0 };
    state.validationLevel = GeospatialValidationLevel_BloomFilter;
    TraverseBsonByPath(document, &pathView, &ValidateGeographyCoordinates, &state);
    PG_RETURN_BOOL(state.isValidGeometry);
}
```

## 第20页 共60页

### 查询规划器 - documents_planner.c

```c
#include <postgres.h>
#include <float.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <bson.h>
#include <catalog/pg_am.h>
#include <catalog/pg_class.h>
#include <storage/lmgr.h>
#include <optimizer/planner.h>
#include "optimizer/pathnode.h"
#include <nodes/nodes.h>
#include <nodes/makefuncs.h>
#include <nodes/nodeFuncs.h>
#include <nodes/parsenodes.h>
#include <nodes/print.h>
#include <parser/parse_target.h>
#include <storage/lockdefs.h>
#include <tcop/utility.h>
#include <utils/builtins.h>
#include <utils/lsyscache.h>
#include <utils/syscache.h>
#include <executor/spi.h>
#include <parser/parse_relation.h>
#include "geospatial/bson_geospatial_geonear.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "planner/documentdb_planner.h"
#include "query/query_operator.h"
#include "opclass/bson_index_support.h"
#include "opclass/bson_gin_index_mgmt.h"
#include "metadata/index.h"
#include "customscan/bson_custom_scan.h"
#include "customscan/bson_custom_query_scan.h"
#include "opclass/bson_text_gin.h"
#include "aggregation/bson_aggregation_pipeline.h"
#include "utils/query_utils.h"
#include "api_hooks.h"
#include "query/bson_compare.h"
#include "planner/documents_custom_planner.h"
typedef enum MongoQueryFlag
{
    HAS_QUERY_OPERATOR = 1 << 0,
    HAS_MONGO_COLLECTION_RTE = 1 << 2,
    HAS_CURSOR_STATE_PARAM = 1 << 3,
    HAS_CURSOR_FUNC = 1 << 4,
    HAS_AGGREGATION_FUNCTION = 1 << 5,
    HAS_NESTED_AGGREGATION_FUNCTION = 1 << 6,
    HAS_QUERY_MATCH_FUNCTION = 1 << 7
} MongoQueryFlag;
typedef struct ReplaceMongoCollectionContext
{
    bool isNonExistentCollection;
    ParamListInfo boundParams;
    Query *query;
} ReplaceMongoCollectionContext;
typedef struct MongoQueryFlagsState
{
    int mongoQueryFlags;
    int queryDepth;
} MongoQueryFlagsState;
static bool MongoQueryFlagsWalker(Node *node, MongoQueryFlagsState *queryFlags);
static int MongoQueryFlags(Query *query);
static bool IsReadWriteCommand(Query *query);
static Query * ReplaceMongoCollectionFunction(Query *query, ParamListInfo boundParams,
                                              bool *isNonExistentCollection);
static bool ReplaceMongoCollectionFunctionWalker(Node *node,
                                                 ReplaceMongoCollectionContext *context);
static bool HasUnresolvedExternParamsWalker(Node *expression, ParamListInfo boundParams);
static bool IsRTEShardForMongoCollection(RangeTblEntry *rte, bool *isMongoDataNamespace,
                                         uint64 *collectionId);
static bool ProcessWorkerWriteQueryPath(PlannerInfo *root, RelOptInfo *rel, Index rti,
                                        RangeTblEntry *rte);
static void ExpandAggregationFunction(PlannerInfo *root, RelOptInfo *rel, Index rti,
                                     RangeTblEntry *rte);
static void ForceExcludeNonIndexPaths(PlannerInfo *root, RelOptInfo *rel, Index rti,
                                     RangeTblEntry *rte);
PlannedStmt *
DocumentDBApiPlanner(Query *parse, const char *query_string, int cursorOptions,
                     ParamListInfo boundParams)
{
    bool isNonExistentCollection = false;
    Query *modifiedQuery = ReplaceMongoCollectionFunction(parse, boundParams,
                                                         &isNonExistentCollection);
    if (isNonExistentCollection)
    {
        return CreateEmptyPlan(modifiedQuery, query_string, cursorOptions, boundParams);
    }
    int mongoQueryFlags = MongoQueryFlags(modifiedQuery);
    if (mongoQueryFlags & HAS_AGGREGATION_FUNCTION)
    {
        modifiedQuery = ExpandAggregationFunction(modifiedQuery, boundParams);
    }
    if (mongoQueryFlags & HAS_QUERY_OPERATOR)
    {
        modifiedQuery = ReplaceBsonQueryOperators(modifiedQuery, boundParams);
    }
    return standard_planner(modifiedQuery, query_string, cursorOptions, boundParams);
}
bool
TryExtractDataFromRestrictInfo(RestrictInfo *restrictInfo, Expr **leftExpr,
                              Expr **rightExpr, Oid *operatorId)
{
    if (restrictInfo == NULL || restrictInfo->clause == NULL)
    {
        return false;
    }
    Expr *clause = restrictInfo->clause;
    if (!IsA(clause, OpExpr))
    {
        return false;
    }
    OpExpr *opExpr = (OpExpr *) clause;
    if (list_length(opExpr->args) != 2)
    {
        return false;
    }
    *leftExpr = (Expr *) linitial(opExpr->args);
    *rightExpr = (Expr *) lsecond(opExpr->args);
    *operatorId = opExpr->opno;
    return true;
}
int
MongoQueryFlags(Query *query)
{
    MongoQueryFlagsState queryFlags = { 0 };
    query_tree_walker(query, MongoQueryFlagsWalker, &queryFlags, 0);
    return queryFlags.mongoQueryFlags;
}
bool
IsAggregationFunction(FuncExpr *funcExpr)
{
    return IsAggregationFunctionByName(get_func_name(funcExpr->funcid));
}
```

## 第21页 共60页

### BSON GIN索引操作 - bson_gin_core.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <access/reloptions.h>
#include <executor/executor.h>
#include <utils/builtins.h>
#include <utils/typcache.h>
#include <utils/lsyscache.h>
#include <utils/syscache.h>
#include <utils/timestamp.h>
#include <utils/array.h>
#include <parser/parse_coerce.h>
#include <catalog/pg_type.h>
#include <funcapi.h>
#include <lib/stringinfo.h>
#include "opclass/bson_gin_common.h"
#include "opclass/bson_gin_private.h"
#include "opclass/bson_gin_index_mgmt.h"
#include "opclass/bson_gin_index_term.h"
#include "opclass/bson_gin_index_types_core.h"
#include "io/bson_core.h"
#include "aggregation/bson_query_common.h"
#include "query/bson_compare.h"
#include "query/bson_dollar_operators.h"
#include "query/query_operator.h"
#include "utils/documentdb_errors.h"
#include <math.h>
typedef struct
{
    union
    {
        BsonElemMatchIndexExprState exprEvalState;
        RegexData *regexData;
    };
    bool isExprEvalState;
} BsonDollarAllIndexState;
typedef struct DollarRangeValues
{
    DollarRangeParams params;
    bool isArrayTerm;
    bytea *maxValueIndexTerm;
    bytea *minValueIndexTerm;
} DollarRangeValues;
typedef struct DollarArrayOpQueryData
{
    bool arrayHasNull;
    bool arrayHasRegex;
    bool arrayHasElemMatch;
    bool arrayHasTruncation;
    int inTermCount;
    int rootTermIndex;
    int rootExistsTermIndex;
    int rootNullTermIndex;
    int rootEmptyArrayTermIndex;
    int rootUndefinedTermIndex;
    int rootRegexTermIndex;
    int rootElemMatchTermIndex;
} DollarArrayOpQueryData;
typedef struct DollarExistsQueryData
{
    bool hasExistsTrue;
    bool hasExistsFalse;
    int existsTrueTermIndex;
    int existsFalseTermIndex;
    int undefinedTermIndex;
} DollarExistsQueryData;
static Datum * GenerateTermsCore(pgbson *document, int32 *nkeys,
                                bool isNested, bool isWildcardIndex);
static bool GinBsonExtractQueryGreaterEqual(pgbson *queryValue, int32 *nkeys,
                                           Datum **entries, bool **nullFlags,
                                           int32 **searchMode, Pointer **extra_data);
static StrategyNumber GinBsonComparePartialGreater(Datum term, Datum query,
                                                  StrategyNumber strategy,
                                                  Pointer extra_data);
static StrategyNumber GinBsonComparePartialLess(Datum term, Datum query,
                                               StrategyNumber strategy,
                                               Pointer extra_data);
static StrategyNumber GinBsonComparePartialDollarRange(Datum term, Datum query,
                                                      StrategyNumber strategy,
                                                      Pointer extra_data);
static StrategyNumber GinBsonComparePartialExists(Datum term, Datum query,
                                                 StrategyNumber strategy,
                                                 Pointer extra_data);
static StrategyNumber GinBsonComparePartialSize(Datum term, Datum query,
                                               StrategyNumber strategy,
                                               Pointer extra_data);
static StrategyNumber GinBsonComparePartialType(Datum term, Datum query,
                                               StrategyNumber strategy,
                                               Pointer extra_data);
static StrategyNumber GinBsonComparePartialRegex(Datum term, Datum query,
                                                StrategyNumber strategy,
                                                Pointer extra_data);
static StrategyNumber GinBsonComparePartialMod(Datum term, Datum query,
                                              StrategyNumber strategy,
                                              Pointer extra_data);
static StrategyNumber GinBsonComparePartialBitsWiseOperator(Datum term, Datum query,
                                                           StrategyNumber strategy,
                                                           Pointer extra_data);
static void ProcessExtractQueryForRegex(RegexData *regexData);
static bytea * GenerateEmptyArrayTerm(void);
static void GenerateNullEqualityIndexTerms(Datum **entries, bool **nullFlags,
                                          int32 **searchMode, Pointer **extra_data,
                                          int32 *nkeys);
static void GenerateExistsEqualityTerms(Datum **entries, bool **nullFlags,
                                       int32 **searchMode, Pointer **extra_data,
                                       int32 *nkeys, bool existsValue,
                                       DollarExistsQueryData *existsQueryData,
                                       bool isWildcardIndex);
static void GenerateTermPath(StringInfo termPath, const char *path,
                            bool isNested, bool isWildcardIndex,
                            bool isArrayIndex, int arrayIndex);
bool
IsWildcardIndex(Relation indexRelation)
{
    if (indexRelation == NULL)
    {
        return false;
    }
    Oid indexRelationId = RelationGetRelid(indexRelation);
    List *indexList = RelationGetIndexList(indexRelation);
    ListCell *indexOid;
    foreach(indexOid, indexList)
    {
        Oid currentIndexOid = lfirst_oid(indexOid);
        if (currentIndexOid == indexRelationId)
        {
            continue;
        }
        Relation currentIndexRelation = index_open(currentIndexOid, AccessShareLock);
        bool isWildcard = RelationGetForm(currentIndexRelation)->relam == GIN_AM_OID;
        index_close(currentIndexRelation, AccessShareLock);
        if (isWildcard)
        {
            list_free(indexList);
            return true;
        }
    }
    list_free(indexList);
    return false;
}
bool
HandleConsistentEqualsNull(bool *check, bool *recheck, StrategyNumber strategy,
                          bool nullCategory, Datum queryKey, Datum entryKey,
                          DollarArrayOpQueryData *arrayOpQueryData)
{
    if (strategy == BsonEqualStrategyNumber)
    {
        if (nullCategory)
        {
            *check = true;
            *recheck = false;
            return true;
        }
        if (arrayOpQueryData != NULL && arrayOpQueryData->arrayHasNull)
        {
            *check = true;
            *recheck = true;
            return true;
        }
    }
    return false;
}
bool
HandleConsistentGreaterLessEquals(bool *check, bool *recheck, StrategyNumber strategy,
                                 bool nullCategory, Datum queryKey, Datum entryKey)
{
    if (strategy == BsonGreaterEqualStrategyNumber ||
        strategy == BsonGreaterStrategyNumber ||
        strategy == BsonLessEqualStrategyNumber ||
        strategy == BsonLessStrategyNumber)
    {
        if (nullCategory)
        {
            *check = false;
            *recheck = false;
            return true;
        }
    }
    return false;
}
bool
HandleConsistentExists(bool *check, bool *recheck, StrategyNumber strategy,
                      bool nullCategory, Datum queryKey, Datum entryKey,
                      DollarExistsQueryData *existsQueryData)
{
    if (strategy == BsonExistsStrategyNumber)
    {
        if (nullCategory)
        {
            *check = false;
            *recheck = false;
            return true;
        }
        bool existsValue = DatumGetBool(queryKey);
        if (existsValue)
        {
            *check = true;
            *recheck = false;
            return true;
        }
        else
        {
            *check = false;
            *recheck = false;
            return true;
        }
    }
    return false;
}
```

## 第22页 共60页

### 自定义扫描节点 - custom_query_scan.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <utils/lsyscache.h>
#include <nodes/extensible.h>
#include <nodes/makefuncs.h>
#include <nodes/nodeFuncs.h>
#include <optimizer/pathnode.h>
#include <optimizer/optimizer.h>
#include <parser/parse_relation.h>
#include <utils/rel.h>
#include <access/detoast.h>
#include <miscadmin.h>
#include <optimizer/paths.h>
#include <access/ginblock.h>
#include "io/bson_core.h"
#include "customscan/bson_custom_query_scan.h"
#include "customscan/custom_scan_registrations.h"
#include "metadata/metadata_cache.h"
#include "query/query_operator.h"
#include "catalog/pg_am.h"
#include "commands/cursor_common.h"
#include "vector/vector_planner.h"
#include "vector/vector_common.h"
#include "vector/vector_spec.h"
#include "utils/documentdb_errors.h"
#include "customscan/bson_custom_scan_private.h"
QueryTextIndexData *QueryTextData = NULL;
typedef struct InputQueryState
{
    ExtensibleNode extensible;
    union
    {
        QueryTextIndexData queryTextData;
        SearchQueryEvalData querySearchData;
    };
    bool hasQueryTextData;
    bool hasVectorSearchData;
} InputQueryState;
typedef struct ExtensionQueryScanState
{
    CustomScanState custom_scanstate;
    ScanState *innerScanState;
    Plan *innerPlan;
    InputQueryState *inputState;
} ExtensionQueryScanState;
#define InputContinuationNodeName "ExtensionQueryScanInput"
static CustomPath * ExtensionQueryScanPlanCustomPath(PlannerInfo *root,
                                                     RelOptInfo *rel,
                                                     struct CustomPath *best_path,
                                                     List *tlist,
                                                     List *clauses,
                                                     List *custom_plans);
static Node * ExtensionQueryScanBeginCustomScan(CustomScanState *node,
                                                EState *estate, int eflags);
static void ExtensionQueryScanExplainCustomScan(CustomScanState *node,
                                                List *ancestors,
                                                ExplainState *es);
static Node * CopyNodeInputQueryState(const Node *from);
static bool EqualUnsupportedExtensionQueryScanNode(const Node *a,
                                                   const Node *b);
static void AddCustomPathForVectorCore(PlannerInfo *root, RelOptInfo *rel,
                                      Index rti, RangeTblEntry *rte,
                                      SearchQueryEvalData *searchQueryData);
static CustomScanMethods ExtensionQueryScanMethods = {
    .CustomName = "ExtensionQueryScan",
    .CreateCustomScanState = ExtensionQueryScanBeginCustomScan,
};
static CustomExecMethods ExtensionQueryScanExecMethods = {
    .CustomName = "ExtensionQueryScan",
    .BeginCustomScan = ExtensionQueryScanBeginCustomScan,
    .ExecCustomScan = ExtensionQueryScanNextRecheck,
    .EndCustomScan = ExtensionQueryScanEndCustomScan,
    .ReScanCustomScan = ExtensionQueryScanReScanCustomScan,
    .MarkPosCustomScan = NULL,
    .RestrPosCustomScan = NULL,
    .EstimateDSMCustomScan = NULL,
    .InitializeDSMCustomScan = NULL,
    .ReInitializeDSMCustomScan = NULL,
    .InitializeWorkerCustomScan = NULL,
    .ShutdownCustomScan = NULL,
    .ExplainCustomScan = ExtensionQueryScanExplainCustomScan,
};
static ExtensibleNodeMethods InputQueryStateMethods = {
    .extnodename = InputContinuationNodeName,
    .node_size = sizeof(InputQueryState),
    .nodeCopy = CopyNodeInputQueryState,
    .nodeEqual = EqualUnsupportedExtensionQueryScanNode,
    .nodeOut = OutInputQueryScanNode,
    .nodeRead = ReadUnsupportedExtensionQueryScanNode,
};
void
RegisterQueryScanNodes(void)
{
    RegisterCustomScanMethods(&ExtensionQueryScanMethods);
    RegisterExtensibleNodeMethods(&InputQueryStateMethods);
}
void
AddExtensionQueryScanForVectorQuery(PlannerInfo *root, RelOptInfo *rel,
                                   Index rti, RangeTblEntry *rte)
{
    SearchQueryEvalData *searchQueryData = GetSearchQueryEvalData();
    if (searchQueryData == NULL)
    {
        return;
    }
    AddCustomPathForVectorCore(root, rel, rti, rte, searchQueryData);
}
void
AddExtensionQueryScanForTextQuery(PlannerInfo *root, RelOptInfo *rel,
                                 Index rti, RangeTblEntry *rte)
{
    if (QueryTextData == NULL)
    {
        return;
    }
    InputQueryState *inputState = makeNode(InputQueryState);
    inputState->extensible.extnodename = InputContinuationNodeName;
    inputState->hasQueryTextData = true;
    inputState->hasVectorSearchData = false;
    inputState->queryTextData = *QueryTextData;
    CustomPath *customPath = makeNode(CustomPath);
    customPath->path.pathtype = T_CustomScan;
    customPath->path.parent = rel;
    customPath->path.pathtarget = rel->reltarget;
    customPath->path.param_info = NULL;
    customPath->path.parallel_aware = false;
    customPath->path.parallel_safe = rel->consider_parallel;
    customPath->path.parallel_workers = 0;
    customPath->path.rows = rel->rows;
    customPath->path.startup_cost = 0;
    customPath->path.total_cost = rel->rows;
    customPath->flags = 0;
    customPath->custom_paths = NIL;
    customPath->custom_private = list_make1(inputState);
    customPath->methods = &ExtensionQueryScanMethods;
    add_path(rel, (Path *) customPath);
}
Node *
ExtensionQueryScanBeginCustomScan(CustomScanState *node, EState *estate, int eflags)
{
    ExtensionQueryScanState *scanState = (ExtensionQueryScanState *) node;
    InputQueryState *inputState = (InputQueryState *) linitial(node->custom_ps);
    scanState->inputState = inputState;
    if (inputState->hasQueryTextData)
    {
        QueryTextData = &inputState->queryTextData;
    }
    if (inputState->hasVectorSearchData)
    {
        SetSearchQueryEvalData(&inputState->querySearchData);
    }
    Plan *innerPlan = (Plan *) linitial(node->custom_ps);
    scanState->innerPlan = innerPlan;
    scanState->innerScanState = ExecInitNode(innerPlan, estate, eflags);
    return (Node *) scanState;
}
TupleTableSlot *
ExtensionQueryScanNextRecheck(CustomScanState *node)
{
    ExtensionQueryScanState *scanState = (ExtensionQueryScanState *) node;
    return ExecProcNode(scanState->innerScanState);
}
void
ExtensionQueryScanEndCustomScan(CustomScanState *node)
{
    ExtensionQueryScanState *scanState = (ExtensionQueryScanState *) node;
    ExecEndNode(scanState->innerScanState);
}
void
ExtensionQueryScanReScanCustomScan(CustomScanState *node)
{
    ExtensionQueryScanState *scanState = (ExtensionQueryScanState *) node;
    ExecReScan(scanState->innerScanState);
}
```

## 第23页 共60页

### 功能特性配置 - feature_flag_configs.c

```c
#include <postgres.h>
#include <miscadmin.h>
#include <utils/guc.h>
#include <limits.h>
#include "configs/config_initialization.h"
#define DEFAULT_ENABLE_SCHEMA_VALIDATION false
bool EnableSchemaValidation =
    DEFAULT_ENABLE_SCHEMA_VALIDATION;
#define DEFAULT_ENABLE_BYPASSDOCUMENTVALIDATION false
bool EnableBypassDocumentValidation =
    DEFAULT_ENABLE_BYPASSDOCUMENTVALIDATION;
#define DEFAULT_ENABLE_NATIVE_TABLE_COLOCATION false
bool EnableNativeTableColocation = DEFAULT_ENABLE_NATIVE_TABLE_COLOCATION;
#define DEFAULT_ENABLE_USERNAME_PASSWORD_CONSTRAINTS true
bool EnableUsernamePasswordConstraints = DEFAULT_ENABLE_USERNAME_PASSWORD_CONSTRAINTS;
#define DEFAULT_ENABLE_USERS_INFO_PRIVILEGES true
bool EnableUsersInfoPrivileges = DEFAULT_ENABLE_USERS_INFO_PRIVILEGES;
#define DEFAULT_ENABLE_VECTOR_HNSW_INDEX true
bool EnableVectorHNSWIndex = DEFAULT_ENABLE_VECTOR_HNSW_INDEX;
#define DEFAULT_ENABLE_VECTOR_PRE_FILTER true
bool EnableVectorPreFilter = DEFAULT_ENABLE_VECTOR_PRE_FILTER;
#define DEFAULT_ENABLE_VECTOR_PRE_FILTER_V2 false
bool EnableVectorPreFilterV2 = DEFAULT_ENABLE_VECTOR_PRE_FILTER_V2;
#define DEFAULT_ENABLE_VECTOR_FORCE_INDEX_PUSHDOWN false
bool EnableVectorForceIndexPushdown = DEFAULT_ENABLE_VECTOR_FORCE_INDEX_PUSHDOWN;
#define DEFAULT_ENABLE_VECTOR_COMPRESSION_HALF true
bool EnableVectorCompressionHalf = DEFAULT_ENABLE_VECTOR_COMPRESSION_HALF;
#define DEFAULT_ENABLE_VECTOR_COMPRESSION_PQ true
bool EnableVectorCompressionPQ = DEFAULT_ENABLE_VECTOR_COMPRESSION_PQ;
#define DEFAULT_ENABLE_VECTOR_CALCULATE_DEFAULT_SEARCH_PARAM true
bool EnableVectorCalculateDefaultSearchParameter =
    DEFAULT_ENABLE_VECTOR_CALCULATE_DEFAULT_SEARCH_PARAM;
#define DEFAULT_ENABLE_LARGE_UNIQUE_INDEX_KEYS true
bool DefaultEnableLargeUniqueIndexKeys = DEFAULT_ENABLE_LARGE_UNIQUE_INDEX_KEYS;
#define DEFAULT_ENABLE_RUM_IN_OPERATOR_FAST_PATH true
bool EnableRumInOperatorFastPath = DEFAULT_ENABLE_RUM_IN_OPERATOR_FAST_PATH;
#define DEFAULT_ENABLE_INDEX_TERM_TRUNCATION_NESTED_OBJECTS true
bool EnableIndexTermTruncationOnNestedObjects =
    DEFAULT_ENABLE_INDEX_TERM_TRUNCATION_NESTED_OBJECTS;
#define DEFAULT_ENABLE_INDEX_OPERATOR_BOUNDS true
bool EnableIndexOperatorBounds = DEFAULT_ENABLE_INDEX_OPERATOR_BOUNDS;
#define DEFAULT_USE_UNSAFE_INDEX_TERM_TRANSFORM true
bool IndexTermUseUnsafeTransform = DEFAULT_USE_UNSAFE_INDEX_TERM_TRANSFORM;
#define DEFAULT_FORCE_RUM_ORDERED_INDEX_SCAN false
bool ForceRumOrderedIndexScan = DEFAULT_FORCE_RUM_ORDERED_INDEX_SCAN;
#define DEFAULT_ENABLE_NEW_OPERATOR_SELECTIVITY false
bool EnableNewOperatorSelectivityMode = DEFAULT_ENABLE_NEW_OPERATOR_SELECTIVITY;
#define DEFAULT_ENABLE_RUM_INDEX_SCAN true
bool EnableRumIndexScan = DEFAULT_ENABLE_RUM_INDEX_SCAN;
#define DEFAULT_ENABLE_MULTI_INDEX_RUM_JOIN false
bool EnableMultiIndexRumJoin = DEFAULT_ENABLE_MULTI_INDEX_RUM_JOIN;
#define DEFAULT_ENABLE_SORT_BY_ID_PUSHDOWN_TO_PRIMARYKEY true
bool EnableSortByIdPushdownToPrimaryKey = DEFAULT_ENABLE_SORT_BY_ID_PUSHDOWN_TO_PRIMARYKEY;
#define DEFAULT_USE_NEW_ELEMMATCH_INDEX_PUSHDOWN true
bool UseNewElemMatchIndexPushdown = DEFAULT_USE_NEW_ELEMMATCH_INDEX_PUSHDOWN;
#define DEFAULT_ENABLE_NOW_SYSTEM_VARIABLE true
bool EnableNowSystemVariable = DEFAULT_ENABLE_NOW_SYSTEM_VARIABLE;
#define DEFAULT_ENABLE_MATCH_WITH_LET_IN_LOOKUP true
bool EnableMatchWithLetInLookup = DEFAULT_ENABLE_MATCH_WITH_LET_IN_LOOKUP;
#define DEFAULT_ENABLE_PRIMARY_KEY_CURSOR_SCAN true
bool EnablePrimaryKeyCursorScan = DEFAULT_ENABLE_PRIMARY_KEY_CURSOR_SCAN;
#define DEFAULT_USE_RAW_EXECUTOR_FOR_QUERY_PLAN false
bool UseRawExecutorForQueryPlan = DEFAULT_USE_RAW_EXECUTOR_FOR_QUERY_PLAN;
#define DEFAULT_USE_FILE_BASED_PERSISTED_CURSORS true
bool UseFileBasedPersistedCursors = DEFAULT_USE_FILE_BASED_PERSISTED_CURSORS;
#define DEFAULT_ENABLE_FILE_BASED_PERSISTED_CURSORS true
bool EnableFileBasedPersistedCursors = DEFAULT_ENABLE_FILE_BASED_PERSISTED_CURSORS;
#define DEFAULT_ENABLE_COMPACT_COMMAND false
bool EnableCompactCommand = DEFAULT_ENABLE_COMPACT_COMMAND;
#define DEFAULT_EXPAND_DOLLAR_ALL_IN_QUERY_OPERATOR true
bool ExpandDollarAllInQueryOperator = DEFAULT_EXPAND_DOLLAR_ALL_IN_QUERY_OPERATOR;
#define DEFAULT_USE_LEGACY_ORDERBY_BEHAVIOR false
bool UseLegacyOrderByBehavior = DEFAULT_USE_LEGACY_ORDERBY_BEHAVIOR;
#define DEFAULT_USE_LEGACY_NULL_EQUALITY_BEHAVIOR false
bool UseLegacyNullEqualityBehavior = DEFAULT_USE_LEGACY_NULL_EQUALITY_BEHAVIOR;
#define DEFAULT_ENABLE_LET_AND_COLLATION_FOR_QUERY_MATCH true
bool EnableLetAndCollationForQueryMatch = DEFAULT_ENABLE_LET_AND_COLLATION_FOR_QUERY_MATCH;
#define DEFAULT_ENABLE_VARIABLES_SUPPORT_FOR_WRITE_COMMANDS true
bool EnableVariablesSupportForWriteCommands =
    DEFAULT_ENABLE_VARIABLES_SUPPORT_FOR_WRITE_COMMANDS;
#define DEFAULT_SKIP_FAIL_ON_COLLATION false
bool SkipFailOnCollation = DEFAULT_SKIP_FAIL_ON_COLLATION;
#define DEFAULT_ENABLE_LOOKUP_ID_JOIN_OPTIMIZATION_ON_COLLATION true
bool EnableLookupIdJoinOptimizationOnCollation =
    DEFAULT_ENABLE_LOOKUP_ID_JOIN_OPTIMIZATION_ON_COLLATION;
#define DEFAULT_RECREATE_RETRY_TABLE_ON_SHARDING false
bool RecreateRetryTableOnSharding = DEFAULT_RECREATE_RETRY_TABLE_ON_SHARDING;
#define DEFAULT_ENABLE_MERGE_TARGET_CREATION true
bool EnableMergeTargetCreation = DEFAULT_ENABLE_MERGE_TARGET_CREATION;
#define DEFAULT_ENABLE_MERGE_ACROSS_DB false
bool EnableMergeAcrossDb = DEFAULT_ENABLE_MERGE_ACROSS_DB;
#define DEFAULT_ENABLE_STATEMENT_TIMEOUT true
bool EnableStatementTimeout = DEFAULT_ENABLE_STATEMENT_TIMEOUT;
#define ALTER_CREATION_TIME_IN_COMPLETE_UPGRADE false
bool AlterCreationTimeInCompleteUpgrade = ALTER_CREATION_TIME_IN_COMPLETE_UPGRADE;
#define DEFAULT_ENABLE_DATA_TABLES_WITHOUT_CREATION_TIME false
bool EnableDataTablesWithoutCreationTime =
    DEFAULT_ENABLE_DATA_TABLES_WITHOUT_CREATION_TIME;
#define DEFAULT_ENABLE_MULTIPLE_INDEX_BUILDS_PER_RUN true
bool EnableMultipleIndexBuildsPerRun = DEFAULT_ENABLE_MULTIPLE_INDEX_BUILDS_PER_RUN;
#define DEFAULT_SKIP_ENFORCE_TRANSACTION_READ_ONLY false
bool SkipEnforceTransactionReadOnly = DEFAULT_SKIP_ENFORCE_TRANSACTION_READ_ONLY;
#define DEFAULT_SKIP_CREATE_INDEXES_ON_CREATE_COLLECTION false
bool SkipCreateIndexesOnCreateCollection = DEFAULT_SKIP_CREATE_INDEXES_ON_CREATE_COLLECTION;
#define DEFAULT_USE_NEW_SHARD_KEY_CALCULATION true
bool UseNewShardKeyCalculation = DEFAULT_USE_NEW_SHARD_KEY_CALCULATION;
#define DEFAULT_ENABLE_BUCKET_AUTO_STAGE false
bool EnableBucketAutoStage = DEFAULT_ENABLE_BUCKET_AUTO_STAGE;
void
InitializeFeatureFlagConfigurations(void)
{
    DefineCustomBoolVariable("documentdb.enable_schema_validation",
                            "Enable schema validation for collections",
                            NULL,
                            &EnableSchemaValidation,
                            DEFAULT_ENABLE_SCHEMA_VALIDATION,
                            PGC_USERSET,
                            0,
                            NULL,
                            NULL,
                            NULL);
    DefineCustomBoolVariable("documentdb.enable_vector_hnsw_index",
                            "Enable HNSW index type for vector search",
                            NULL,
                            &EnableVectorHNSWIndex,
                            DEFAULT_ENABLE_VECTOR_HNSW_INDEX,
                            PGC_USERSET,
                            0,
                            NULL,
                            NULL,
                            NULL);
    DefineCustomBoolVariable("documentdb.enable_vector_pre_filter",
                            "Enable vector pre-filtering feature",
                            NULL,
                            &EnableVectorPreFilter,
                            DEFAULT_ENABLE_VECTOR_PRE_FILTER,
                            PGC_USERSET,
                            0,
                            NULL,
                            NULL,
                            NULL);
    DefineCustomBoolVariable("documentdb.enable_rum_index_scan",
                            "Enable RUM index scan optimization",
                            NULL,
                            &EnableRumIndexScan,
                            DEFAULT_ENABLE_RUM_INDEX_SCAN,
                            PGC_USERSET,
                            0,
                            NULL,
                            NULL,
                            NULL);
    DefineCustomBoolVariable("documentdb.use_file_based_persisted_cursors",
                            "Use file-based cursor persistence",
                            NULL,
                            &UseFileBasedPersistedCursors,
                            DEFAULT_USE_FILE_BASED_PERSISTED_CURSORS,
                            PGC_USERSET,
                            0,
                            NULL,
                            NULL,
                            NULL);
}
```

## 第24页 共60页

### 后台工作进程 - background_worker.c

```c
#include <postgres.h>
#include <catalog/pg_extension.h>
#include <nodes/pg_list.h>
#include <tcop/utility.h>
#include <postmaster/interrupt.h>
#include <storage/latch.h>
#include <miscadmin.h>
#include <postmaster/bgworker.h>
#include <storage/shmem.h>
#include <storage/ipc.h>
#include <postmaster/postmaster.h>
#include <utils/backend_status.h>
#include <utils/wait_event.h>
#include <utils/memutils.h>
#include <utils/timestamp.h>
#include <utils/builtins.h>
#include <access/xact.h>
#include <utils/snapmgr.h>
#include "commands/connection_management.h"
#include "metadata/metadata_cache.h"
#include "api_hooks.h"
#include "utils/documentdb_errors.h"
#define ONE_SEC_IN_MS 1000L
typedef struct BackgroundWorkerShmemStruct
{
    Latch latch;
} BackgroundWorkerShmemStruct;
PGDLLEXPORT void DocumentDBBackgroundWorkerMain(Datum);
extern char *BackgroundWorkerDatabaseName;
extern int LatchTimeOutSec;
static bool BackgroundWorkerReloadConfig = false;
static BackgroundWorkerShmemStruct *BackgroundWorkerShmem;
static Size BackgroundWorkerShmemSize(void);
static void BackgroundWorkerShmemInit(void);
static void BackgroundWorkerKill(int code, Datum arg);
static volatile sig_atomic_t got_sigterm = false;
static void background_worker_sigterm(SIGNAL_ARGS);
static void background_worker_sighup(SIGNAL_ARGS);
static char ExtensionBackgroundWorkerLeaderName[50];
void
DocumentDBBackgroundWorkerMain(Datum main_arg)
{
    char *databaseName = BackgroundWorkerDatabaseName;
    pqsignal(SIGINT, SIG_IGN);
    pqsignal(SIGTERM, background_worker_sigterm);
    pqsignal(SIGHUP, background_worker_sighup);
    BackgroundWorkerUnblockSignals();
    BackgroundWorkerInitializeConnection(databaseName, NULL, 0);
    if (strlen(ExtensionObjectPrefixV2) + strlen("_bg_worker_leader") + 1 >
        sizeof(ExtensionBackgroundWorkerLeaderName))
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
                        errmsg(
                            "Unexpected - ExtensionObjectPrefix is too long for background worker leader name"),
                        errdetail_log(
                            "Unexpected - ExtensionObjectPrefix %s is too long for background worker leader name",
                            ExtensionObjectPrefixV2)));
    }
    snprintf(ExtensionBackgroundWorkerLeaderName,
             sizeof(ExtensionBackgroundWorkerLeaderName),
             "%s_bg_worker_leader", ExtensionObjectPrefixV2);
    ereport(LOG, (errmsg("Starting %s with databaseName %s",
                         ExtensionBackgroundWorkerLeaderName, databaseName)));
    pgstat_report_appname(ExtensionBackgroundWorkerLeaderName);
    BackgroundWorkerShmemInit();
    OwnLatch(&BackgroundWorkerShmem->latch);
    on_shmem_exit(BackgroundWorkerKill, 0);
    int waitResult;
    int latchTimeOut = LatchTimeOutSec;
    while (!got_sigterm)
    {
        waitResult = 0;
        if (BackgroundWorkerReloadConfig)
        {
            ProcessConfigFile(PGC_SIGHUP);
            BackgroundWorkerReloadConfig = false;
        }
        waitResult = WaitLatch(&BackgroundWorkerShmem->latch,
                               WL_LATCH_SET | WL_TIMEOUT | WL_EXIT_ON_PM_DEATH,
                               latchTimeOut * ONE_SEC_IN_MS,
                               WAIT_EVENT_PG_SLEEP);
        ResetLatch(&BackgroundWorkerShmem->latch);
        CHECK_FOR_INTERRUPTS();
        if (waitResult & WL_LATCH_SET)
        {
        }
        if ((waitResult & WL_TIMEOUT))
        {
        }
        latchTimeOut = LatchTimeOutSec;
    }
    ereport(LOG, (errmsg("%s is shutting down.",
                         ExtensionBackgroundWorkerLeaderName)));
}
static Size
BackgroundWorkerShmemSize(void)
{
    Size size;
    size = sizeof(BackgroundWorkerShmemStruct);
    size = MAXALIGN(size);
    return size;
}
static void
BackgroundWorkerShmemInit(void)
{
    bool found;
    BackgroundWorkerShmem = (BackgroundWorkerShmemStruct *) ShmemInitStruct(
        "DocumentDB Background Worker data",
        BackgroundWorkerShmemSize(),
        &found);
    if (!found)
    {
        MemSet(BackgroundWorkerShmem, 0, BackgroundWorkerShmemSize());
        InitSharedLatch(&BackgroundWorkerShmem->latch);
    }
}
static void
BackgroundWorkerKill(int code, Datum arg)
{
    Assert(BackgroundWorkerShmem != NULL);
    BackgroundWorkerShmemStruct *backgroundWorkerShmem = BackgroundWorkerShmem;
    BackgroundWorkerShmem = NULL;
    DisownLatch(&backgroundWorkerShmem->latch);
}
static void
background_worker_sigterm(SIGNAL_ARGS)
{
    got_sigterm = true;
    ereport(LOG,
            (errmsg("Terminating \"%s\" due to administrator command",
                    ExtensionBackgroundWorkerLeaderName)));
    if (BackgroundWorkerShmem != NULL)
    {
        SetLatch(&BackgroundWorkerShmem->latch);
    }
}
static void
background_worker_sighup(SIGNAL_ARGS)
{
    BackgroundWorkerReloadConfig = true;
    if (BackgroundWorkerShmem != NULL)
    {
        SetLatch(&BackgroundWorkerShmem->latch);
    }
}
```

## 第25页 共60页

### 游标存储基础设施 - cursor_store.c

```c
#include <postgres.h>
#include <miscadmin.h>
#include <storage/sharedfileset.h>
#include <storage/dsm.h>
#include <storage/buffile.h>
#include <utils/resowner.h>
#include <utils/wait_event.h>
#include <port.h>
#include <utils/timestamp.h>
#include <utils/resowner.h>
#include <port/atomics.h>
#include <storage/lwlock.h>
#include <storage/shmem.h>
#include <utils/backend_status.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include "metadata/metadata_cache.h"
#include "utils/documentdb_errors.h"
#include "io/bson_core.h"
#include "infrastructure/cursor_store.h"
extern char *ApiGucPrefix;
extern bool UseFileBasedPersistedCursors;
extern bool EnableFileBasedPersistedCursors;
extern int MaxAllowedCursorIntermediateFileSizeMB;
extern int DefaultCursorExpiryTimeLimitSeconds;
extern int MaxCursorFileCount;
typedef struct SerializedCursorState
{
    char cursorFileName[NAMEDATALEN];
    uint32_t file_offset;
    uint32_t file_length;
} SerializedCursorState;
typedef struct CursorFileState
{
    SerializedCursorState cursorState;
    File bufFile;
    bool isReadWrite;
    PGAlignedBlock buffer;
    int pos;
    int nbytes;
    uint32_t next_offset;
    bool cursorComplete;
} CursorFileState;
typedef struct CursorStoreSharedData
{
    int sharedCursorStoreTrancheId;
    char *sharedCursorStoreTrancheName;
    LWLock sharedCursorStoreLock;
    int32_t currentCursorCount;
    int32_t cleanupCursorFileCount;
    int64_t cleanupTotalCursorSize;
} CursorStoreSharedData;
static CursorStoreSharedData *CursorStoreSharedState = NULL;
static char *CursorDirectoryPath = NULL;
static void cursor_directory_cleanup(void);
void
SetupCursorStorage(void)
{
    if (!EnableFileBasedPersistedCursors)
    {
        return;
    }
    if (CursorDirectoryPath != NULL)
    {
        return;
    }
    StringInfo cursorDirectoryPath = makeStringInfo();
    appendStringInfo(cursorDirectoryPath, "%s/documentdb_cursors_%d",
                     DataDir, MyProcPid);
    CursorDirectoryPath = cursorDirectoryPath->data;
    if (mkdir(CursorDirectoryPath, S_IRWXU) != 0)
    {
        if (errno != EEXIST)
        {
            ereport(ERROR,
                    (errcode_for_file_access(),
                     errmsg("could not create directory \"%s\": %m",
                            CursorDirectoryPath)));
        }
    }
    on_proc_exit(cursor_directory_cleanup, 0);
}
static void
cursor_directory_cleanup(void)
{
    if (CursorDirectoryPath == NULL)
    {
        return;
    }
    DIR *dir = opendir(CursorDirectoryPath);
    if (dir == NULL)
    {
        return;
    }
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL)
    {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
        {
            continue;
        }
        StringInfo filePath = makeStringInfo();
        appendStringInfo(filePath, "%s/%s", CursorDirectoryPath, entry->d_name);
        if (unlink(filePath->data) != 0)
        {
            ereport(WARNING,
                    (errcode_for_file_access(),
                     errmsg("could not remove file \"%s\": %m", filePath->data)));
        }
        pfree(filePath->data);
        pfree(filePath);
    }
    closedir(dir);
    if (rmdir(CursorDirectoryPath) != 0)
    {
        ereport(WARNING,
                (errcode_for_file_access(),
                 errmsg("could not remove directory \"%s\": %m",
                        CursorDirectoryPath)));
    }
}
void
WriteToCursorFile(CursorFileState *cursorFileState, const char *data, int len)
{
    if (!cursorFileState->isReadWrite)
    {
        ereport(ERROR,
                (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
                 errmsg("Cannot write to cursor file in read-only mode")));
    }
    while (len > 0)
    {
        int available = BLCKSZ - cursorFileState->pos;
        if (available == 0)
        {
            FlushBuffer(cursorFileState);
            available = BLCKSZ;
        }
        int to_copy = Min(len, available);
        memcpy(cursorFileState->buffer.data + cursorFileState->pos, data, to_copy);
        cursorFileState->pos += to_copy;
        data += to_copy;
        len -= to_copy;
    }
}
int32_t
GetCurrentCursorCount(void)
{
    if (CursorStoreSharedState == NULL)
    {
        return 0;
    }
    LWLockAcquire(&CursorStoreSharedState->sharedCursorStoreLock, LW_SHARED);
    int32_t count = CursorStoreSharedState->currentCursorCount;
    LWLockRelease(&CursorStoreSharedState->sharedCursorStoreLock);
    return count;
}
void
DeletePendingCursorFiles(void)
{
    if (CursorStoreSharedState == NULL)
    {
        return;
    }
    LWLockAcquire(&CursorStoreSharedState->sharedCursorStoreLock, LW_EXCLUSIVE);
    CursorStoreSharedState->cleanupCursorFileCount = 0;
    CursorStoreSharedState->cleanupTotalCursorSize = 0;
    LWLockRelease(&CursorStoreSharedState->sharedCursorStoreLock);
}
void
DeleteCursorFile(const char *cursorFileName)
{
    if (CursorDirectoryPath == NULL)
    {
        return;
    }
    StringInfo filePath = makeStringInfo();
    appendStringInfo(filePath, "%s/%s", CursorDirectoryPath, cursorFileName);
    if (unlink(filePath->data) != 0 && errno != ENOENT)
    {
        ereport(WARNING,
                (errcode_for_file_access(),
                 errmsg("could not remove cursor file \"%s\": %m", filePath->data)));
    }
    pfree(filePath->data);
    pfree(filePath);
}
```

## 第26页 共60页

### 分片功能 - sharding.c

```c
#include <math.h>
#include <postgres.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <executor/spi.h>
#include <lib/stringinfo.h>
#include <utils/builtins.h>
#include <nodes/makefuncs.h>
#include "io/bson_core.h"
#include "api_hooks.h"
#include "commands/create_indexes.h"
#include "utils/documentdb_errors.h"
#include "sharding/sharding.h"
#include "metadata/metadata_cache.h"
#include "utils/query_utils.h"
#include "commands/parse_error.h"
#include "commands/commands_common.h"
#include "metadata/collection.h"
#include "collation/collation.h"
extern bool EnableNativeColocation;
extern int ShardingMaxChunks;
extern bool RecreateRetryTableOnSharding;
extern bool UseNewShardKeyCalculation;
typedef struct ShardKeyMetadata
{
    const char **fields;
    int fieldCount;
} ShardKeyMetadata;
typedef struct ShardKeyFieldValues
{
    bson_value_t *values;
    int *setCount;
} ShardKeyFieldValues;
typedef struct ShardKeyInValueCount
{
    bson_value_t *values;
    int valueCount;
} ShardKeyInValueCount;
typedef enum ShardCollectionMode
{
    ShardCollectionMode_Shard = 1,
    ShardCollectionMode_Reshard = 2,
    ShardCollectionMode_Unshard = 3,
} ShardCollectionMode;
typedef struct ShardCollectionArgs
{
    char *databaseName;
    char *collectionName;
    pgbson *shardKeyDefinition;
    int numInitialChunks;
    ShardCollectionMode mode;
} ShardCollectionArgs;
static void InitShardKeyMetadata(ShardKeyMetadata *metadata, pgbson *shardKey);
static void InitShardKeyFieldValues(ShardKeyFieldValues *values, int fieldCount);
static ShardKeyFieldValues * CloneShardKeyFieldValues(
    const ShardKeyFieldValues *source, int fieldCount);
static uint32_t ComputeShardKeyFieldValuesHash(
    const ShardKeyFieldValues *values,
    const ShardKeyMetadata *metadata);
static void FindShardKeyFieldValuesForQuery(ShardKeyFieldValues *values,
                                           const ShardKeyMetadata *metadata,
                                           pgbson *query);
static void FindShardKeyValuesExpr(ShardKeyFieldValues *values,
                                  const ShardKeyMetadata *metadata,
                                  bson_iter_t *queryIter,
                                  const char *currentPath);
static void FindShardKeyValuesExprNew(ShardKeyFieldValues *values,
                                     const ShardKeyMetadata *metadata,
                                     bson_iter_t *queryIter);
PG_FUNCTION_INFO_V1(command_shard_collection);
Datum
command_shard_collection(PG_FUNCTION_ARGS)
{
    pgbson *argument = PG_GETARG_PGBSON(0);
    ShardCollectionArgs args = { 0 };
    ParseShardCollectionRequest(argument, &args);
    args.mode = ShardCollectionMode_Shard;
    if (EnableNativeColocation)
    {
        ShardCollectionCore(&args);
    }
    else
    {
        ShardCollectionLegacy(&args);
    }
    pgbson *result = PgbsonInitEmpty();
    PgbsonWriterAppendBool(result, "ok", 1, true);
    PG_RETURN_POINTER(result);
}
PG_FUNCTION_INFO_V1(command_reshard_collection);
Datum
command_reshard_collection(PG_FUNCTION_ARGS)
{
    pgbson *argument = PG_GETARG_PGBSON(0);
    ShardCollectionArgs args = { 0 };
    ParseReshardCollectionRequest(argument, &args);
    args.mode = ShardCollectionMode_Reshard;
    if (EnableNativeColocation)
    {
        ShardCollectionCore(&args);
    }
    else
    {
        ereport(ERROR,
                (errcode(ERRCODE_DOCUMENTDB_COMMANDNOTSUPPORTED),
                 errmsg("reshardCollection is not supported in legacy mode")));
    }
    pgbson *result = PgbsonInitEmpty();
    PgbsonWriterAppendBool(result, "ok", 1, true);
    PG_RETURN_POINTER(result);
}
PG_FUNCTION_INFO_V1(command_unshard_collection);
Datum
command_unshard_collection(PG_FUNCTION_ARGS)
{
    pgbson *argument = PG_GETARG_PGBSON(0);
    ShardCollectionArgs args = { 0 };
    ParseUnshardCollectionRequest(argument, &args);
    args.mode = ShardCollectionMode_Unshard;
    if (EnableNativeColocation)
    {
        ShardCollectionCore(&args);
    }
    else
    {
        ereport(ERROR,
                (errcode(ERRCODE_DOCUMENTDB_COMMANDNOTSUPPORTED),
                 errmsg("unshardCollection is not supported in legacy mode")));
    }
    pgbson *result = PgbsonInitEmpty();
    PgbsonWriterAppendBool(result, "ok", 1, true);
    PG_RETURN_POINTER(result);
}
PG_FUNCTION_INFO_V1(command_get_shard_key_value);
Datum
command_get_shard_key_value(PG_FUNCTION_ARGS)
{
    pgbson *document = PG_GETARG_PGBSON(0);
    pgbson *shardKey = PG_GETARG_PGBSON(1);
    uint32_t hash = ComputeShardKeyHashForDocument(document, shardKey);
    PG_RETURN_INT32(hash);
}
uint32_t
ComputeShardKeyHashForDocument(pgbson *document, pgbson *shardKey)
{
    if (UseNewShardKeyCalculation)
    {
        ShardKeyMetadata metadata = { 0 };
        InitShardKeyMetadata(&metadata, shardKey);
        ShardKeyFieldValues values = { 0 };
        InitShardKeyFieldValues(&values, metadata.fieldCount);
        bson_iter_t documentIter;
        PgbsonInitIterator(document, &documentIter);
        while (bson_iter_next(&documentIter))
        {
            const char *key = bson_iter_key(&documentIter);
            int fieldIndex = ShardKeyFieldIndex(&metadata, key);
            if (fieldIndex >= 0)
            {
                bson_value_copy(bson_iter_value(&documentIter),
                               &values.values[fieldIndex]);
                values.setCount[fieldIndex] = 1;
            }
        }
        return ComputeShardKeyFieldValuesHash(&values, &metadata);
    }
    else
    {
        return ComputeShardKeyHashForDocumentLegacy(document, shardKey);
    }
}
int
FindShardKeyFieldValue(const ShardKeyMetadata *metadata, const char *fieldName)
{
    for (int i = 0; i < metadata->fieldCount; i++)
    {
        if (strcmp(metadata->fields[i], fieldName) == 0)
        {
            return i;
        }
    }
    return -1;
}
PG_FUNCTION_INFO_V1(command_validate_shard_key);
Datum
command_validate_shard_key(PG_FUNCTION_ARGS)
{
    pgbson *shardKey = PG_GETARG_PGBSON(0);
    ValidateShardKey(shardKey);
    PG_RETURN_BOOL(true);
}
void
ValidateShardKey(pgbson *shardKey)
{
    bson_iter_t shardKeyIter;
    PgbsonInitIterator(shardKey, &shardKeyIter);
    while (bson_iter_next(&shardKeyIter))
    {
        const char *key = bson_iter_key(&shardKeyIter);
        if (strlen(key) == 0)
        {
            ereport(ERROR,
                    (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                     errmsg("Shard key field name cannot be empty")));
        }
        if (strchr(key, '.') != NULL)
        {
            ereport(ERROR,
                    (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                     errmsg("Shard key field name cannot contain dots")));
        }
        bson_value_t *value = (bson_value_t *) bson_iter_value(&shardKeyIter);
        if (value->value_type != BSON_TYPE_INT32 || value->value.v_int32 != 1)
        {
            ereport(ERROR,
                    (errcode(ERRCODE_DOCUMENTDB_BADVALUE),
                     errmsg("Shard key field value must be 1")));
        }
    }
}
```

## 第27页 共60页

### API钩子函数 - api_hooks.c

```c
#include <postgres.h>
#include <miscadmin.h>
#include <utils/guc.h>
#include <limits.h>
#include "index_am/documentdb_rum.h"
#include "metadata/collection.h"
#include "metadata/index.h"
#include "io/bson_core.h"
#include "lib/stringinfo.h"
#include "api_hooks.h"
#include "api_hooks_def.h"
#include "utils/query_utils.h"
#include "utils/documentdb_errors.h"
#include "vector/vector_spec.h"
IsMetadataCoordinator_HookType is_metadata_coordinator_hook = NULL;
RunCommandOnMetadataCoordinator_HookType run_command_on_metadata_coordinator_hook = NULL;
RunQueryWithCommutativeWrites_HookType run_query_with_commutative_writes_hook = NULL;
RunQueryWithSequentialModification_HookType
    run_query_with_sequential_modification_mode_hook = NULL;
DistributePostgresTable_HookType distribute_postgres_table_hook = NULL;
ModifyTableColumnNames_HookType modify_table_column_names_hook = NULL;
RunQueryWithNestedDistribution_HookType run_query_with_nested_distribution_hook = NULL;
AllowNestedDistributionInCurrentTransaction_HookType
    allow_nested_distribution_in_current_transaction_hook = NULL;
IsShardTableForMongoTable_HookType is_shard_table_for_mongo_table_hook = NULL;
HandleColocation_HookType handle_colocation_hook = NULL;
RewriteListCollectionsQueryForDistribution_HookType rewrite_list_collections_query_hook =
    NULL;
RewriteConfigQueryForDistribution_HookType rewrite_config_shards_query_hook = NULL;
RewriteConfigQueryForDistribution_HookType rewrite_config_chunks_query_hook = NULL;
TryGetShardNameForUnshardedCollection_HookType
    try_get_shard_name_for_unsharded_collection_hook = NULL;
GetDistributedApplicationName_HookType get_distributed_application_name_hook = NULL;
IsChangeStreamEnabledAndCompatible is_changestream_enabled_and_compatible_hook = NULL;
IsNtoReturnSupported_HookType is_n_to_return_supported_hook = NULL;
EnsureMetadataTableReplicated_HookType ensure_metadata_table_replicated_hook = NULL;
PostSetupCluster_HookType post_setup_cluster_hook = NULL;
GetIndexAmRoutine_HookType get_index_amroutine_hook = NULL;
GetMultiAndBitmapIndexFunc_HookType get_multi_and_bitmap_func_hook = NULL;
TryCustomParseAndValidateVectorQuerySpec_HookType
    try_custom_parse_and_validate_vector_query_spec_hook = NULL;
TryOptimizePathForBitmapAndHookType try_optimize_path_for_bitmap_and_hook = NULL;
TryGetExtendedVersionRefreshQuery_HookType try_get_extended_version_refresh_query_hook =
    NULL;
GetShardIdsAndNamesForCollection_HookType get_shard_ids_and_names_for_collection_hook =
    NULL;
CreateUserWithExernalIdentityProvider_HookType
    create_user_with_exernal_identity_provider_hook = NULL;
DropUserWithExernalIdentityProvider_HookType
    drop_user_with_exernal_identity_provider_hook = NULL;
GetUserInfoFromExternalIdentityProvider_HookType
    get_user_info_from_external_identity_provider_hook = NULL;
IsUserExternal_HookType
    is_user_external_hook = NULL;
GetPidForIndexBuild_HookType get_pid_for_index_build_hook = NULL;
TryGetIndexBuildJobOpIdQuery_HookType try_get_index_build_job_op_id_query_hook =
    NULL;
TryGetCancelIndexBuildQuery_HookType try_get_cancel_index_build_query_hook =
    NULL;
ShouldScheduleIndexBuilds_HookType should_schedule_index_builds_hook = NULL;
UserNameValidation_HookType
    username_validation_hook = NULL;
PasswordValidation_HookType
    password_validation_hook = NULL;
bool
IsMetadataCoordinator(void)
{
    if (is_metadata_coordinator_hook != NULL)
    {
        return is_metadata_coordinator_hook();
    }
    return true;
}
DistributedRunCommandResult
RunCommandOnMetadataCoordinator(const char *query)
{
    if (run_command_on_metadata_coordinator_hook != NULL)
    {
        return run_command_on_metadata_coordinator_hook(query);
    }
    DistributedRunCommandResult result = { 0 };
    result.success = false;
    result.errorMessage = "No distributed coordinator available";
    return result;
}
void
RunQueryWithCommutativeWrites(const char *query, List *parameterList)
{
    if (run_query_with_commutative_writes_hook != NULL)
    {
        run_query_with_commutative_writes_hook(query, parameterList);
        return;
    }
    ereport(ERROR,
            (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
             errmsg("Commutative writes not supported in single node mode")));
}
void
RunMultiValueQueryWithNestedDistribution(const char *query,
                                        List *parameterList,
                                        Datum *datums,
                                        bool *isNull,
                                        int numValues)
{
    if (run_query_with_nested_distribution_hook != NULL)
    {
        run_query_with_nested_distribution_hook(query, parameterList,
                                               datums, isNull, numValues);
        return;
    }
    ExtensionExecuteMultiValueQueryWithArgsViaSPI(query, true, SPI_OK_SELECT,
                                                 datums, isNull, numValues,
                                                 parameterList);
}
bool
AllowNestedDistributionInCurrentTransaction(void)
{
    if (allow_nested_distribution_in_current_transaction_hook != NULL)
    {
        return allow_nested_distribution_in_current_transaction_hook();
    }
    return false;
}
void
RunQueryWithSequentialModification(const char *query, List *parameterList)
{
    if (run_query_with_sequential_modification_mode_hook != NULL)
    {
        run_query_with_sequential_modification_mode_hook(query, parameterList);
        return;
    }
    ExtensionExecuteQueryWithArgsViaSPI(query, false, SPI_OK_SELECT, parameterList);
}
bool
IsShardTableForMongoTable(Oid relationId, char *databaseName, char *collectionName)
{
    if (is_shard_table_for_mongo_table_hook != NULL)
    {
        return is_shard_table_for_mongo_table_hook(relationId, databaseName,
                                                  collectionName);
    }
    return false;
}
```

## 第28页 共60页

### 错误处理工具 - error_utils.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <utils/builtins.h>
#include "utils/documentdb_errors.h"
#include "utils/version_utils.h"
PG_FUNCTION_INFO_V1(command_convert_mongo_error_to_postgres);
PG_FUNCTION_INFO_V1(command_throw_mongo_error);
Datum
pg_attribute_noreturn()
command_throw_mongo_error(PG_FUNCTION_ARGS)
{
    ereport(ERROR, (errcode(ERRCODE_WARNING_DEPRECATED_FEATURE),
                    errmsg("command_throw_mongo_error function is deprecated now")));
}
Datum
command_convert_mongo_error_to_postgres(PG_FUNCTION_ARGS)
{
    ereport(ERROR, (errcode(ERRCODE_WARNING_DEPRECATED_FEATURE),
                    errmsg("command_convert_mongo_error_to_postgres "
                           "function is deprecated now")));
}
```

## 第29页 共60页

### 查询执行工具 - query_utils.c

```c
#include <postgres.h>
#include <libpq-fe.h>
#include <miscadmin.h>
#include <catalog/pg_type.h>
#include <commands/dbcommands.h>
#include <common/username.h>
#include <executor/spi.h>
#include <postmaster/postmaster.h>
#include <storage/latch.h>
#include <utils/array.h>
#include <utils/datum.h>
#include <utils/syscache.h>
#include <utils/wait_event.h>
#include "commands/connection_management.h"
#include "utils/query_utils.h"
#include "api_hooks.h"
#include "metadata/metadata_cache.h"
extern char *LocalhostConnectionString;
char *SerialExecutionFlags = NULL;
static Datum SPIReturnDatum(bool *isNull, int position);
static char * ExtensionExecuteQueryViaLibPQ(char *query, char *connStr);
static char * ExtensionExecuteQueryWithArgsViaLibPQ(char *query, char *connStr, int
                                                    nParams, Oid *paramTypes, const
                                                    char **parameterValues);
static void PGConnFinishConnectionEstablishment(PGconn *conn);
static void PGConnFinishIO(PGconn *conn);
static char * PGConnReturnFirstField(PGconn *conn);
static void PGConnReportError(PGconn *conn, PGresult *result, int elevel);
static char * GetLocalhostConnStr(const Oid userOid, bool useSerialExecution);
Datum
ExtensionExecuteQueryViaSPI(const char *query, bool readOnly, int expectedSPIOK,
                            bool *isNull)
{
    if (SPI_connect() != SPI_OK_CONNECT)
    {
        ereport(ERROR, (errmsg("could not connect to SPI manager")));
    }
    ereport(DEBUG1, (errmsg("executing \"%s\" via SPI", query)));
    int tupleCountLimit = 1;
    int spiErrorCode = SPI_execute(query, readOnly, tupleCountLimit);
    if (spiErrorCode != expectedSPIOK)
    {
        ereport(ERROR, (errmsg("could not run SPI query %d", spiErrorCode)));
    }
    Datum retDatum = SPIReturnDatum(isNull, 1);
    if (SPI_finish() != SPI_OK_FINISH)
    {
        ereport(ERROR, (errmsg("could not finish SPI connection")));
    }
    return retDatum;
}
void
ExtensionExecuteMultiValueQueryViaSPI(const char *query, bool readOnly, int expectedSPIOK,
                                      Datum *datums, bool *isNull, int numValues)
{
    if (SPI_connect() != SPI_OK_CONNECT)
    {
        ereport(ERROR, (errmsg("could not connect to SPI manager")));
    }
    ereport(DEBUG1, (errmsg("executing \"%s\" via SPI", query)));
    int tupleCountLimit = 1;
    int spiErrorCode = SPI_execute(query, readOnly, tupleCountLimit);
    if (spiErrorCode != expectedSPIOK)
    {
        ereport(ERROR, (errmsg("could not run SPI query %d", spiErrorCode)));
    }
    for (int i = 0; i < numValues; i++)
    {
        datums[i] = SPIReturnDatum(&isNull[i], i + 1);
    }
    if (SPI_finish() != SPI_OK_FINISH)
    {
        ereport(ERROR, (errmsg("could not finish SPI connection")));
    }
}
Datum
ExtensionExecuteQueryWithArgsViaSPI(const char *query, bool readOnly, int expectedSPIOK,
                                   List *parameterList)
{
    if (SPI_connect() != SPI_OK_CONNECT)
    {
        ereport(ERROR, (errmsg("could not connect to SPI manager")));
    }
    ereport(DEBUG1, (errmsg("executing \"%s\" via SPI with args", query)));
    int nargs = list_length(parameterList);
    Oid *argtypes = NULL;
    Datum *values = NULL;
    char *nulls = NULL;
    if (nargs > 0)
    {
        argtypes = (Oid *) palloc(nargs * sizeof(Oid));
        values = (Datum *) palloc(nargs * sizeof(Datum));
        nulls = (char *) palloc(nargs * sizeof(char));
        ListCell *parameterCell;
        int argIndex = 0;
        foreach(parameterCell, parameterList)
        {
            SPIQueryParameter *parameter = (SPIQueryParameter *) lfirst(parameterCell);
            argtypes[argIndex] = parameter->parameterType;
            values[argIndex] = parameter->parameterValue;
            nulls[argIndex] = parameter->isNull ? 'n' : ' ';
            argIndex++;
        }
    }
    int tupleCountLimit = 1;
    int spiErrorCode = SPI_execute_with_args(query, nargs, argtypes, values, nulls,
                                           readOnly, tupleCountLimit);
    if (spiErrorCode != expectedSPIOK)
    {
        ereport(ERROR, (errmsg("could not run SPI query with args %d", spiErrorCode)));
    }
    bool isNull;
    Datum retDatum = SPIReturnDatum(&isNull, 1);
    if (SPI_finish() != SPI_OK_FINISH)
    {
        ereport(ERROR, (errmsg("could not finish SPI connection")));
    }
    return retDatum;
}
static Datum
SPIReturnDatum(bool *isNull, int position)
{
    if (SPI_processed == 0)
    {
        *isNull = true;
        return (Datum) 0;
    }
    if (position > SPI_tuptable->tupdesc->natts)
    {
        ereport(ERROR, (errmsg("position %d exceeds number of attributes %d",
                               position, SPI_tuptable->tupdesc->natts)));
    }
    HeapTuple tuple = SPI_tuptable->vals[0];
    TupleDesc tupdesc = SPI_tuptable->tupdesc;
    return SPI_getbinval(tuple, tupdesc, position, isNull);
}
```

## 第30页 共60页

### 索引工具函数 - index_utils.c

```c
#include <postgres.h>
#include <storage/proc.h>
#include <utils/snapmgr.h>
#include <tcop/pquery.h>
#include "utils/index_utils.h"
void
set_indexsafe_procflags(void)
{
    Assert(MyProc->xid == InvalidTransactionId &&
           MyProc->xmin == InvalidTransactionId);
    LWLockAcquire(ProcArrayLock, LW_EXCLUSIVE);
    MyProc->statusFlags |= PROC_IN_SAFE_IC;
    ProcGlobal->statusFlags[MyProc->pgxactoff] = MyProc->statusFlags;
    LWLockRelease(ProcArrayLock);
}
void
PopAllActiveSnapshots(void)
{
    while (ActiveSnapshotSet())
    {
        PopActiveSnapshot();
    }
    if (ActivePortal != NULL)
    {
        ActivePortal->portalSnapshot = NULL;
    }
}
```

## 第31页 共60页

### 存储工具函数 - storage_utils.c

```c
#include "utils/storage_utils.h"
#include "api_hooks.h"
#include "commands/diagnostic_commands_common.h"
#include "io/bson_core.h"
#include "io/bsonvalue_utils.h"
#include "utils/documentdb_errors.h"
#include "utils/guc_utils.h"
#include "utils/query_utils.h"
#include "metadata/metadata_cache.h"
static CollectionBloatStats MergeBloatStatsBsons(List *workerBsons);
PG_FUNCTION_INFO_V1(get_bloat_stats_worker);
Datum
get_bloat_stats_worker(PG_FUNCTION_ARGS)
{
    uint64 collectionId = PG_GETARG_INT64(0);
    MongoCollection *collection = GetMongoCollectionByColId(collectionId,
                                                            AccessShareLock);
    ArrayType *shardNames = NULL;
    ArrayType *shardOids = NULL;
    GetMongoCollectionShardOidsAndNames(collection, &shardOids, &shardNames);
    if (shardNames == NULL)
    {
        return PointerGetDatum(PgbsonInitEmpty());
    }
    StringInfo bloatEstimateQuery = makeStringInfo();
    appendStringInfo(bloatEstimateQuery,
                     "WITH constants AS ("
                     "   SELECT %d AS bs, 23 AS hdr, 8 AS ma"
                     "),",
                     BLCKSZ);
    appendStringInfo(bloatEstimateQuery,
                     "null_headers AS ("
                     "   SELECT "
                     "   hdr+1+(sum(case when null_frac <> 0 THEN 1 else 0 END)/8) as nullhdr, "
                     "   SUM((1-null_frac)*avg_width) as datawidth, "
                     "   MAX(null_frac) as maxfracsum,"
                     "   schemaname, tablename, hdr, ma, bs "
                     "   FROM pg_stats CROSS JOIN constants "
                     "   WHERE schemaname = %s"
                     "   AND tablename = ANY ($1)"
                     "   GROUP BY schemaname, tablename, hdr, ma, bs ), ",
                     quote_literal_cstr(ApiDataSchemaName));
    appendStringInfo(bloatEstimateQuery,
                     " data_headers AS ( "
                     "   SELECT "
                     "   ma, bs, hdr, schemaname, tablename, "
                     "   (datawidth+(hdr+ma-(case when hdr%%ma=0 THEN ma ELSE hdr%%ma END)))::numeric AS datahdr, "
                     "   (maxfracsum*(nullhdr+ma-(case when nullhdr%%ma=0 THEN ma ELSE nullhdr%%ma END))) AS nullhdr2 "
                     "   FROM null_headers "
                     "),"
                     "table_estimates AS ( "
                     "   SELECT schemaname, tablename, bs, "
                     "   reltuples::numeric as est_rows, relpages * bs as table_bytes, "
                     "   CEIL((reltuples* "
                     "       (datahdr + nullhdr2 + 4 + ma - "
                     "        (CASE WHEN datahdr%%ma=0 "
                     "            THEN ma ELSE datahdr%%ma END)"
                     "        )/(bs-20))) * bs AS expected_bytes, "
                     "   reltoastrelid "
                     "   FROM data_headers "
                     "   JOIN pg_class ON tablename = relname "
                     "   JOIN pg_namespace ON relnamespace = pg_namespace.oid "
                     "   AND schemaname = nspname "
                     "   WHERE pg_class.relkind = 'r' "
                     "),"
                     "estimates_with_toast AS ( "
                     "   SELECT schemaname, tablename, "
                     "        TRUE as can_estimate,"
                     "        est_rows,"
                     "        table_bytes + ( coalesce(toast.relpages, 0) * bs ) as table_bytes,"
                     "        expected_bytes + ( ceil( coalesce(toast.reltuples, 0) / 4 ) * bs ) as expected_bytes"
                     "    FROM table_estimates LEFT OUTER JOIN pg_class as toast"
                     "        ON table_estimates.reltoastrelid = toast.oid"
                     "            AND toast.relkind = 't'"
                     "),"
                     "table_estimates_plus AS ("
                     "    SELECT current_database() as databasename,"
                     "            schemaname, tablename, can_estimate, "
                     "            est_rows,"
                     "            CASE WHEN table_bytes > 0"
                     "                THEN table_bytes::NUMERIC"
                     "                ELSE NULL::NUMERIC END"
                     "                AS table_bytes,"
                     "            CASE WHEN expected_bytes > 0 "
                     "                THEN expected_bytes::NUMERIC"
                     "                ELSE NULL::NUMERIC END"
                     "                    AS expected_bytes,"
                     "            CASE WHEN expected_bytes > 0 AND table_bytes > 0"
                     "                AND expected_bytes <= table_bytes"
                     "                THEN (table_bytes - expected_bytes)::NUMERIC"
                     "                ELSE 0::NUMERIC END AS bloat_bytes"
                     "    FROM estimates_with_toast"
                     "),"
                     "bloat_data AS ("
                     "    select current_database() as databasename,"
                     "        schemaname, tablename, can_estimate, "
                     "        round(bloat_bytes*100/table_bytes) as pct_bloat,"
                     "        bloat_bytes,"
                     "        table_bytes, expected_bytes, est_rows"
                     "    FROM table_estimates_plus"
                     "),"
                     "projectBloat AS ("
                     "   SELECT "
                     "   SUM(bloat_bytes::int8) as bloat_bytes,"
                     "   SUM(table_bytes::int8) as table_bytes "
                     "   FROM bloat_data"
                     ")"
                     " SELECT %s.row_get_bson(projectBloat) FROM projectBloat",
                     CoreSchemaNameV2);
    int argCount = 1;
    char argNulls[1] = { ' ' };
    Oid argTypes[1] = { TEXTARRAYOID };
    Datum argValues[1] = { PointerGetDatum(shardNames) };
    bool readOnly = true;
    Datum resultDatum[1] = { 0 };
    bool isNulls[1] = { false };
    int numResults = 1;
    RunMultiValueQueryWithNestedDistribution(bloatEstimateQuery->data, argCount, argTypes,
                                             argValues,
                                             argNulls,
                                             readOnly, SPI_OK_SELECT, resultDatum,
                                             isNulls, numResults);
    if (isNulls[0])
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
                        errmsg("Failed to get bloat stats for collection %lu",
                               collectionId)));
    }
    PG_RETURN_POINTER(DatumGetPgBson(resultDatum[0]));
}
CollectionBloatStats
GetCollectionBloatEstimate(uint64 collectionId)
{
    int numValues = 1;
    Datum values[1] = { UInt64GetDatum(collectionId) };
    Oid types[1] = { INT8OID };
    List *workerBsons = RunQueryOnAllServerNodes("BloatStats", values, types, numValues,
                                                 get_bloat_stats_worker,
                                                 ApiInternalSchemaNameV2,
                                                 "get_bloat_stats_worker");
    return MergeBloatStatsBsons(workerBsons);
}
static CollectionBloatStats
MergeBloatStatsBsons(List *workerBsons)
{
    CollectionBloatStats bloatStats;
    memset(&bloatStats, 0, sizeof(CollectionBloatStats));
    bloatStats.nullStats = true;
    ListCell *workerCell;
    foreach(workerCell, workerBsons)
    {
        pgbson *workerBson = lfirst(workerCell);
        bson_iter_t iter;
        PgbsonInitIterator(workerBson, &iter);
        while (bson_iter_next(&iter))
        {
            bloatStats.nullStats = false;
            const char *key = bson_iter_key(&iter);
            const bson_value_t *value = bson_iter_value(&iter);
            if (key[0] == 'b')
            {
                bloatStats.estimatedBloatStorage += BsonValueAsInt64(value);
            }
            else if (key[0] == 't')
            {
                bloatStats.estimatedTableStorage += BsonValueAsInt64(value);
            }
        }
    }
    return bloatStats;
}
```

## 第32页 共60页

### TTL索引管理 - ttl_index.c

```c
#include <postgres.h>
#include <catalog/namespace.h>
#include <commands/sequence.h>
#include <executor/spi.h>
#include <portability/instr_time.h>
#include "io/bson_core.h"
#include "metadata/collection.h"
#include "query/bson_compare.h"
#include "metadata/metadata_cache.h"
#include "storage/lmgr.h"
#include "utils/list_utils.h"
#include "utils/query_utils.h"
#include "utils/feature_counter.h"
#include "utils/guc_utils.h"
#include "utils/error_utils.h"
#include "utils/index_utils.h"
extern bool LogTTLProgressActivity;
extern int TTLPurgerStatementTimeout;
extern int MaxTTLDeleteBatchSize;
extern int TTLPurgerLockTimeout;
extern char *ApiGucPrefix;
extern int SingleTTLTaskTimeBudget;
extern bool EnableTtlJobsOnReadOnly;
bool UseV2TTLIndexPurger = true;
typedef struct TtlIndexEntry
{
    uint64 collectionId;
    uint64 indexId;
    Datum indexKeyDatum;
    Datum indexPfeDatum;
    int32 indexExpireAfterSeconds;
} TtlIndexEntry;
static uint64 DeleteExpiredRowsForIndexCore(char *tableName, TtlIndexEntry *indexEntry,
                                            int64 currentTime, int32 batchSize);
static bool IsTaskTimeBudgetExceeded(instr_time startTime, double *elapsedTime);
PG_FUNCTION_INFO_V1(delete_expired_rows_for_index);
PG_FUNCTION_INFO_V1(delete_expired_rows);
Datum
delete_expired_rows_for_index(PG_FUNCTION_ARGS)
{
    uint64 collectionId = PG_GETARG_INT64(0);
    uint64 indexId = PG_GETARG_INT64(1);
    pgbson *indexKey = PG_GETARG_PGBSON(2);
    pgbson *indexPfe = PG_GETARG_PGBSON(3);
    int32 expireAfterSeconds = PG_GETARG_INT32(4);
    int32 batchSize = PG_GETARG_INT32(5);
    int64 currentTime = PG_GETARG_INT64(6);
    TtlIndexEntry indexEntry = {
        .collectionId = collectionId,
        .indexId = indexId,
        .indexKeyDatum = PgbsonGetDatum(indexKey),
        .indexPfeDatum = PgbsonGetDatum(indexPfe),
        .indexExpireAfterSeconds = expireAfterSeconds
    };
    MongoCollection *collection = GetMongoCollectionByColId(collectionId, AccessShareLock);
    char *tableName = GetCollectionTableName(collection);
    uint64 deletedRows = DeleteExpiredRowsForIndexCore(tableName, &indexEntry,
                                                      currentTime, batchSize);
    PG_RETURN_INT64(deletedRows);
}
static bool
IsTaskTimeBudgetExceeded(instr_time startTime, double *elapsedTime)
{
    instr_time currentTime;
    INSTR_TIME_SET_CURRENT(currentTime);
    INSTR_TIME_SUBTRACT(currentTime, startTime);
    *elapsedTime = INSTR_TIME_GET_MILLISEC(currentTime);
    return *elapsedTime > SingleTTLTaskTimeBudget;
}
static uint64
DeleteExpiredRowsForIndexCore(char *tableName, TtlIndexEntry *indexEntry,
                             int64 currentTime, int32 batchSize)
{
    StringInfo deleteQuery = makeStringInfo();
    int64 expiryTime = currentTime - (indexEntry->indexExpireAfterSeconds * 1000);
    pgbson *expiryBson = PgbsonInitEmpty();
    PgbsonWriterAppendDate(expiryBson, "", 4, expiryTime);
    appendStringInfo(deleteQuery,
                     "WITH deleted_rows AS ("
                     "DELETE FROM %s "
                     "WHERE ctid IN ("
                     "SELECT ctid FROM %s "
                     "WHERE %s.bson_dollar_lt(document, %s) "
                     "LIMIT %d"
                     ") "
                     "RETURNING ctid"
                     ") "
                     "SELECT COUNT(*) FROM deleted_rows",
                     tableName, tableName, ApiCatalogSchemaName,
                     quote_literal_cstr(PgbsonToJsonString(expiryBson)),
                     batchSize);
    bool isNull;
    Datum result = ExtensionExecuteQueryViaSPI(deleteQuery->data, false, SPI_OK_SELECT, &isNull);
    if (isNull)
    {
        return 0;
    }
    return DatumGetInt64(result);
}
```

## 第33页 共60页

### 命令通用函数 - commands_common.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "access/xact.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "utils/builtins.h"
#include "storage/lmgr.h"
#include "utils/snapmgr.h"
#include "io/bson_core.h"
#include "commands/commands_common.h"
#include "utils/error_utils.h"
#include "utils/documentdb_errors.h"
#include "aggregation/bson_query.h"
#include "metadata/metadata_cache.h"
#include "planner/documentdb_planner.h"
#include "utils/timeout.h"
extern bool ThrowDeadlockOnCrud;
extern bool EnableBackendStatementTimeout;
extern int MaxCustomCommandTimeout;
extern bool EnableVariablesSupportForWriteCommands;
static const char *IgnoredCommonSpecFields[] = {
    "$clusterTime",
    "$db",
    "$readPreference",
    "$sort",
    "allowDiskUse",
    "allowPartialResults",
    "apiDeprecationErrors",
    "apiStrict",
    "apiVersion",
    "autocommit",
    "awaitData",
    "batch_size",
    "bypassDocumentValidation",
    "bypassEmptyTsReplacement",
    "collation",
    "collstats",
    "comment",
    "commitQuorum",
    "db",
    "dbstats",
    "flags",
    "indexDetails",
    "let",
    "lsid",
    "maxTimeMS",
    "noCursorTimeout",
    "oplogReplay",
    "options",
    "p5date",
    "pipeline",
    "projection",
    "readConcern",
    "readPreference",
    "returnKey",
    "showRecordId",
    "snapshot",
    "startTransaction",
    "stmtId",
    "storageEngine",
    "symbol",
    "tailable",
    "timeseries",
    "txnNumber",
    "validationAction",
    "validationLevel",
    "validator",
    "viewOn",
    "writeConcern"
};
static int NumberOfIgnoredFields = sizeof(IgnoredCommonSpecFields) / sizeof(char *);
static int CompareStringsCaseInsensitive(const void *a, const void *b);
static pgbson * RewriteDocumentAddObjectIdCore(const bson_value_t *docValue,
                                               bson_value_t *objectIdToWrite);
bool
IsCommonSpecIgnoredField(const char *fieldName)
{
    return bsearch(&fieldName, IgnoredCommonSpecFields, NumberOfIgnoredFields,
                   sizeof(char *), CompareStringsCaseInsensitive) != NULL;
}
void
SetExplicitStatementTimeout(int timeoutMs)
{
    if (EnableBackendStatementTimeout && timeoutMs > 0)
    {
        int clampedTimeout = Min(timeoutMs, MaxCustomCommandTimeout);
        SetStatementTimeout(clampedTimeout);
    }
}
static int
CompareStringsCaseInsensitive(const void *a, const void *b)
{
    const char *str1 = *(const char **) a;
    const char *str2 = *(const char **) b;
    return strcasecmp(str1, str2);
}
```

## 第34页 共60页

### 诊断命令通用函数 - diagnostic_commands_common.c

```c
#include <math.h>
#include <postgres.h>
#include <executor/spi.h>
#include <fmgr.h>
#include <funcapi.h>
#include <utils/builtins.h>
#include <nodes/makefuncs.h>
#include <catalog/namespace.h>
#include <access/xact.h>
#include "metadata/collection.h"
#include "metadata/index.h"
#include "utils/query_utils.h"
#include "utils/feature_counter.h"
#include "planner/documentdb_planner.h"
#include "utils/hashset_utils.h"
#include "utils/version_utils.h"
#include "commands/parse_error.h"
#include "commands/commands_common.h"
#include "commands/diagnostic_commands_common.h"
#include "utils/error_utils.h"
#include "utils/documentdb_errors.h"
List *
RunQueryOnAllServerNodes(const char *commandName, Datum *values, Oid *types,
                         int numValues, PGFunction directFunc,
                         const char *nameSpaceName, const char *functionName)
{
    if (DefaultInlineWriteOperations)
    {
        FunctionCallInfo fcinfo = palloc(SizeForFunctionCallInfo(numValues));
        Datum result;
        InitFunctionCallInfoData(*fcinfo, NULL, numValues, InvalidOid, NULL, NULL);
        for (int i = 0; i < numValues; i++)
        {
            fcinfo->args[i].value = values[i];
            fcinfo->args[i].isnull = false;
        }
        result = (*directFunc)(fcinfo);
        List *resultList = list_make1(DatumGetPgBson(result));
        pfree(fcinfo);
        return resultList;
    }
    StringInfo cmdStr = makeStringInfo();
    appendStringInfo(cmdStr, "SELECT success, result FROM run_command_on_all_nodes("
                             "FORMAT($$ SELECT %s.%s(", nameSpaceName, functionName);
    char *separator = "";
    for (int i = 0; i < numValues; i++)
    {
        appendStringInfo(cmdStr, "%s%%L", separator);
        separator = ",";
    }
    appendStringInfo(cmdStr, ")$$");
    for (int i = 0; i < numValues; i++)
    {
        appendStringInfo(cmdStr, ",$%d", (i + 1));
    }
    appendStringInfo(cmdStr, "))");
    bool readOnly = true;
    List *workerBsons = NIL;
    MemoryContext priorMemoryContext = CurrentMemoryContext;
    SPI_connect();
    Portal workerQueryPortal = SPI_cursor_open_with_args("workerQueryPortal",
                                                         cmdStr->data,
                                                         numValues, types, values,
                                                         NULL, readOnly, 0);
    bool hasData = true;
    while (hasData)
    {
        SPI_cursor_fetch(workerQueryPortal, true, INT_MAX);
        hasData = SPI_processed >= 1;
        if (!hasData)
        {
            break;
        }
        if (SPI_tuptable)
        {
            for (int tupleNumber = 0; tupleNumber < (int) SPI_processed; tupleNumber++)
            {
                bool isNull;
                AttrNumber isSuccessAttr = 1;
                Datum resultDatum = SPI_getbinval(SPI_tuptable->vals[tupleNumber],
                                                  SPI_tuptable->tupdesc, isSuccessAttr,
                                                  &isNull);
                if (isNull)
                {
                    continue;
                }
                bool isSuccess = DatumGetBool(resultDatum);
                if (isSuccess)
                {
                    AttrNumber resultAttribute = 2;
                    resultDatum = SPI_getbinval(SPI_tuptable->vals[tupleNumber],
                                                SPI_tuptable->tupdesc, resultAttribute,
                                                &isNull);
                    if (isNull)
                    {
                        ereport(ERROR, (errmsg(
                                            "%s worker was successful but returned a result null.",
                                            commandName)));
                    }
                    text *resultText = DatumGetTextP(resultDatum);
                    char *resultString = text_to_cstring(resultText);
                    MemoryContext spiContext = MemoryContextSwitchTo(priorMemoryContext);
                    pgbson *bson;
                    if (IsBsonHexadecimalString(resultString))
                    {
                        bson = PgbsonInitFromHexadecimalString(resultString);
                    }
                    else
                    {
                        bson = PgbsonInitFromJson(resultString);
                    }
                    workerBsons = lappend(workerBsons, bson);
                    MemoryContextSwitchTo(spiContext);
                }
                else
                {
                    AttrNumber resultAttribute = 2;
                    resultDatum = SPI_getbinval(SPI_tuptable->vals[tupleNumber],
                                                SPI_tuptable->tupdesc, resultAttribute,
                                                &isNull);
                    if (isNull)
                    {
                        elog(WARNING,
                             "%s worker was not successful but result returned null.",
                             commandName);
                        continue;
                    }
                    text *resultText = DatumGetTextP(resultDatum);
                    const char *workerError = text_to_cstring(resultText);
                    StringView errorView = CreateStringViewFromString(workerError);
                    StringView connectivityView = CreateStringViewFromString(
                        "failed to connect to");
                    StringView recoveryErrorView = CreateStringViewFromString(
                        "terminating connection due to conflict with recovery");
                    StringView recoveryCancelErrorView = CreateStringViewFromString(
                        "canceling statement due to conflict with recovery");
                    StringView outOfMemoryView = CreateStringViewFromString(
                        "out of memory");
                    StringView errorStartView = CreateStringViewFromString(
                        "ERROR: ");
                    if (StringViewStartsWithStringView(&errorView, &errorStartView))
                    {
                        errorView = StringViewSubstring(&errorView,
                                                        errorStartView.length);
                    }
                    if (StringViewStartsWithStringView(&errorView, &connectivityView))
                    {
                        ereport(ERROR, (errcode(ERRCODE_CONNECTION_FAILURE),
                                        errmsg(
                                            "%s on worker failed with connectivity errors",
                                            commandName),
                                        errdetail_log(
                                            "%s on worker failed with an unexpected error: %s",
                                            commandName, workerError)));
                    }
                    else if (StringViewStartsWithStringView(&errorView,
                                                            &recoveryErrorView) ||
                             StringViewStartsWithStringView(&errorView,
                                                            &recoveryCancelErrorView))
                    {
                        ereport(ERROR, (errcode(ERRCODE_T_R_SERIALIZATION_FAILURE),
                                        errmsg(
                                            "%s on worker failed with recovery errors",
                                            commandName),
                                        errdetail_log(
                                            "%s on worker failed with an recovery error: %s",
                                            commandName, workerError)));
                    }
                    else if (StringViewStartsWithStringView(&errorView, &outOfMemoryView))
                    {
                        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_EXCEEDEDMEMORYLIMIT),
                                        errmsg(
                                            "%s on worker failed with out of memory errors",
                                            commandName),
                                        errdetail_log(
                                            "%s on worker failed with an out of memory error: %s",
                                            commandName, workerError)));
                    }
                    else
                    {
                        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
                                        errmsg(
                                            "%s on worker failed with an unexpected error",
                                            commandName),
                                        errdetail_log(
                                            "%s on worker failed with an unexpected error: %s",
                                            commandName, workerError)));
                    }
                }
            }
        }
        else
        {
            ereport(ERROR, (errmsg("%s worker call tuple table was null.", commandName)));
        }
    }
    SPI_cursor_close(workerQueryPortal);
    SPI_finish();
    return workerBsons;
}
pgbson *
RunWorkerDiagnosticLogic(pgbson *(*workerFunc)(void *state), void *state)
{
    MemoryContext savedMemoryContext = CurrentMemoryContext;
    ResourceOwner oldOwner = CurrentResourceOwner;
    pgbson *response = NULL;
    BeginInternalSubTransaction(NULL);
    PG_TRY();
    {
        response = workerFunc(state);
        ReleaseCurrentSubTransaction();
        MemoryContextSwitchTo(savedMemoryContext);
        CurrentResourceOwner = oldOwner;
    }
    PG_CATCH();
    {
        MemoryContextSwitchTo(savedMemoryContext);
        ErrorData *errorData = CopyErrorDataAndFlush();
        RollbackAndReleaseCurrentSubTransaction();
        MemoryContextSwitchTo(savedMemoryContext);
        CurrentResourceOwner = oldOwner;
        pgbson_writer writer;
        PgbsonWriterInit(&writer);
        PgbsonWriterAppendInt32(&writer, ErrCodeKey, ErrCodeLength,
                                errorData->sqlerrcode);
        PgbsonWriterAppendUtf8(&writer, ErrMsgKey, ErrMsgLength, errorData->message);
        response = PgbsonWriterGetPgbson(&writer);
        FreeErrorData(errorData);
    }
    PG_END_TRY();
    return response;
}
```

## 第35页 共60页

### 集合创建核心函数 - create_collection_core.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "utils/builtins.h"
#include "utils/resowner.h"
#include "lib/stringinfo.h"
#include "access/xact.h"
#include "utils/documentdb_errors.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "utils/error_utils.h"
#include "utils/query_utils.h"
#include "api_hooks.h"
extern bool EnableNativeColocation;
extern bool EnableNativeTableColocation;
extern bool EnableDataTableWithoutCreationTime;
static bool CanColocateAtDatabaseLevel(text *databaseDatum);
static const char * CreatePostgresDataTable(uint64_t collectionId,
                                            const char *colocateWith,
                                            const char *shardingColumn);
static uint64_t InsertIntoCollectionTable(text *databaseDatum, text *collectionDatum);
static uint64_t InsertMetadataIntoCollections(text *databaseDatum, text *collectionDatum,
                                              bool *collectionExists);
static const char * GetOrCreateDatabaseConfigCollection(text *databaseDatum);
PG_FUNCTION_INFO_V1(command_create_collection_core);
Datum
command_create_collection_core(PG_FUNCTION_ARGS)
{
    text *databaseDatum = PG_GETARG_TEXT_PP(0);
    text *collectionDatum = PG_GETARG_TEXT_PP(1);
    if (!IsMetadataCoordinator())
    {
        StringInfo createCollectionQuery = makeStringInfo();
        appendStringInfo(createCollectionQuery,
                         "SELECT %s.create_collection(%s,%s)",
                         ApiSchemaName,
                         quote_literal_cstr(text_to_cstring(databaseDatum)),
                         quote_literal_cstr(text_to_cstring(collectionDatum)));
        DistributedRunCommandResult result = RunCommandOnMetadataCoordinator(
            createCollectionQuery->data);
        if (!result.success)
        {
            ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_INTERNALERROR),
                            errmsg(
                                "Internal error creating collection in metadata coordinator %s",
                                text_to_cstring(result.response)),
                            errdetail_log(
                                "Internal error creating collection in metadata coordinator %s",
                                text_to_cstring(result.response))));
        }
        PG_RETURN_BOOL(strcasecmp(text_to_cstring(result.response), "t") == 0);
    }
    MongoCollection *collection = GetMongoCollectionByNameDatum(
        PointerGetDatum(databaseDatum), PointerGetDatum(collectionDatum),
        AccessShareLock);
    if (collection != NULL)
    {
        PG_RETURN_BOOL(false);
    }
    EnsureMetadataTableReplicated("collections");
    const char *colocateWith = NULL;
    const char *shardingColumn = "shard_key_value";
    SetUnshardedColocationData(databaseDatum, &shardingColumn, &colocateWith);
    bool collectionExists = false;
    uint64_t collectionId = InsertMetadataIntoCollections(databaseDatum, collectionDatum,
                                                          &collectionExists);
    if (collectionExists)
    {
        PG_RETURN_BOOL(false);
    }
    CreatePostgresDataTable(collectionId, colocateWith, shardingColumn);
    PG_RETURN_BOOL(true);
}
void
SetUnshardedColocationData(text *databaseDatum, const char **shardingColumn,
                          const char **colocateWith)
{
    if (EnableNativeColocation)
    {
        if (CanColocateAtDatabaseLevel(databaseDatum))
        {
            *colocateWith = GetOrCreateDatabaseConfigCollection(databaseDatum);
        }
        if (EnableNativeTableColocation)
        {
            *shardingColumn = NULL;
        }
    }
}
static uint64_t
InsertMetadataIntoCollections(text *databaseDatum, text *collectionDatum,
                             bool *collectionExists)
{
    StringInfo insertQuery = makeStringInfo();
    appendStringInfo(insertQuery,
                     "INSERT INTO %s.collections (database_name, collection_name) "
                     "VALUES (%s, %s) "
                     "ON CONFLICT (database_name, collection_name) DO NOTHING "
                     "RETURNING collection_id",
                     ApiCatalogSchemaName,
                     quote_literal_cstr(text_to_cstring(databaseDatum)),
                     quote_literal_cstr(text_to_cstring(collectionDatum)));
    bool isNull;
    Datum collectionIdDatum = ExtensionExecuteQueryViaSPI(insertQuery->data, false,
                                                         SPI_OK_INSERT_RETURNING, &isNull);
    if (isNull)
    {
        *collectionExists = true;
        MongoCollection *collection = GetMongoCollectionByNameDatum(
            PointerGetDatum(databaseDatum), PointerGetDatum(collectionDatum),
            AccessShareLock);
        return collection->collectionId;
    }
    *collectionExists = false;
    return DatumGetUInt64(collectionIdDatum);
}
```

## 第36页 共60页

### 文档插入操作 - insert.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <funcapi.h>
#include <nodes/makefuncs.h>
#include <utils/timestamp.h>
#include <utils/portal.h>
#include <tcop/dest.h>
#include <tcop/pquery.h>
#include <tcop/tcopprot.h>
#include <commands/portalcmds.h>
#include <utils/snapmgr.h>
#include <catalog/pg_class.h>
#include <parser/parse_relation.h>
#include <utils/lsyscache.h>
#include "access/xact.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "utils/builtins.h"
#include "io/bson_core.h"
#include "commands/commands_common.h"
#include "commands/insert.h"
#include "commands/parse_error.h"
#include "metadata/collection.h"
#include "infrastructure/documentdb_plan_cache.h"
#include "sharding/sharding.h"
#include "commands/retryable_writes.h"
#include "io/pgbsonsequence.h"
#include "utils/query_utils.h"
#include "utils/feature_counter.h"
#include "metadata/metadata_cache.h"
#include "utils/error_utils.h"
#include "utils/version_utils.h"
#include "utils/documentdb_errors.h"
#include "api_hooks.h"
#include "schema_validation/schema_validation.h"
#include "operators/bson_expr_eval.h"
typedef struct BatchInsertionSpec
{
    char *collectionName;
    List *documents;
    bool isOrdered;
    Oid insertShardOid;
    bool bypassDocumentValidation;
} BatchInsertionSpec;
typedef struct BatchInsertionResult
{
    double ok;
    uint64 rowsInserted;
    List *writeErrors;
    MemoryContext resultMemoryContext;
} BatchInsertionResult;
PG_FUNCTION_INFO_V1(command_insert);
PG_FUNCTION_INFO_V1(command_insert_one);
PG_FUNCTION_INFO_V1(command_insert_worker);
PG_FUNCTION_INFO_V1(command_insert_bulk);
static BatchInsertionSpec * BuildBatchInsertionSpec(bson_iter_t *insertCommandIter,
                                                    pgbsonsequence *insertDocs);
static List * BuildInsertionList(bson_iter_t *insertArrayIter, bool *hasSkippedDocuments);
static List * BuildInsertionListFromPgbsonSequence(pgbsonsequence *docSequence,
                                                   bool *hasSkippedDocuments);
static BatchInsertionResult * ProcessBatchInsertion(BatchInsertionSpec *insertionSpec,
                                                    MongoCollection *collection,
                                                    bool isRetryableWrite,
                                                    uint64 transactionId);
static BatchInsertionResult * DoBatchInsertNoTransactionId(BatchInsertionSpec *insertionSpec,
                                                           MongoCollection *collection,
                                                           bool isRetryableWrite);
static void ProcessInsertion(pgbson *document, MongoCollection *collection,
                            BatchInsertionResult *insertionResult);
static StringInfo CreateInsertQuery(MongoCollection *collection, List *documents,
                                   bool bypassDocumentValidation);
static pgbson * PreprocessInsertionDoc(pgbson *document, MongoCollection *collection,
                                       bool bypassDocumentValidation,
                                       bool *shouldSkipDocument);
static pgbson * InsertOneWithTransactionCore(MongoCollection *collection, pgbson *document,
                                             bool bypassDocumentValidation,
                                             uint64 transactionId);
static pgbson * CallInsertWorkerForInsertOne(MongoCollection *collection, pgbson *document,
                                             bool bypassDocumentValidation);
static pgbson * CommandInsertCore(pgbson *insertSpec);
static StringInfo CreateValuesListForInsert(List *documents, MongoCollection *collection,
                                           bool bypassDocumentValidation);
Datum
command_insert(PG_FUNCTION_ARGS)
{
    pgbson *insertSpec = PG_GETARG_PGBSON(0);
    pgbson *result = CommandInsertCore(insertSpec);
    PG_RETURN_POINTER(result);
}
Datum
command_insert_bulk(PG_FUNCTION_ARGS)
{
    pgbson *insertSpec = PG_GETARG_PGBSON(0);
    pgbsonsequence *insertDocs = PG_GETARG_PGBSONSEQUENCE(1);
    bson_iter_t insertCommandIter;
    PgbsonInitIterator(insertSpec, &insertCommandIter);
    BatchInsertionSpec *insertionSpec = BuildBatchInsertionSpec(&insertCommandIter, insertDocs);
    MongoCollection *collection = GetMongoCollectionByName(insertionSpec->collectionName,
                                                          AccessShareLock);
    if (collection == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_NAMESPACENOTFOUND),
                        errmsg("ns not found")));
    }
    bool isRetryableWrite = false;
    uint64 transactionId = 0;
    BatchInsertionResult *insertionResult = ProcessBatchInsertion(insertionSpec, collection,
                                                                 isRetryableWrite, transactionId);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    PgbsonWriterAppendDouble(&writer, "ok", 2, insertionResult->ok);
    PgbsonWriterAppendInt64(&writer, "n", 1, insertionResult->rowsInserted);
    if (insertionResult->writeErrors != NIL)
    {
        PgbsonWriterStartArray(&writer, "writeErrors", 11);
        ListCell *errorCell;
        foreach(errorCell, insertionResult->writeErrors)
        {
            pgbson *errorBson = (pgbson *) lfirst(errorCell);
            PgbsonWriterAppendValue(&writer, "", 0, PgbsonGetBsonValue(errorBson));
        }
        PgbsonWriterEndArray(&writer);
    }
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
```

## 第37页 共60页

### 文档更新操作 - update.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "funcapi.h"
#include "miscadmin.h"
#include "access/xact.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "utils/builtins.h"
#include "utils/typcache.h"
#include "io/bson_core.h"
#include "aggregation/bson_project.h"
#include "aggregation/bson_query.h"
#include "update/bson_update.h"
#include "commands/commands_common.h"
#include "commands/insert.h"
#include "commands/parse_error.h"
#include "commands/update.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "infrastructure/documentdb_plan_cache.h"
#include "query/query_operator.h"
#include "sharding/sharding.h"
#include "commands/retryable_writes.h"
#include "io/pgbsonsequence.h"
#include "utils/error_utils.h"
#include "utils/feature_counter.h"
#include "utils/query_utils.h"
#include "utils/version_utils.h"
#include "schema_validation/schema_validation.h"
#include "api_hooks.h"
typedef struct BatchUpdateSpec
{
    char *collectionName;
    List *updates;
    bool isOrdered;
    bson_value_t variableSpec;
} BatchUpdateSpec;
typedef struct UpdateSpec
{
    pgbson *queryDocument;
    pgbson *updateDocument;
    bool isUpsert;
    bool isMulti;
    pgbson *arrayFilters;
    pgbson *hint;
    bson_value_t variableSpec;
} UpdateSpec;
typedef struct BatchUpdateResult
{
    double ok;
    uint64 rowsMatched;
    uint64 rowsModified;
    List *upserted;
    List *writeErrors;
} BatchUpdateResult;
PG_FUNCTION_INFO_V1(command_update_bulk);
PG_FUNCTION_INFO_V1(command_update);
PG_FUNCTION_INFO_V1(command_update_one);
PG_FUNCTION_INFO_V1(command_update_worker);
static BatchUpdateSpec * BuildBatchUpdateSpec(bson_iter_t *updateCommandIter,
                                              pgbsonsequence *updateSequence);
static List * BuildUpdateSpecListFromSequence(pgbsonsequence *updateSequence,
                                              bson_value_t *variableSpec);
static BatchUpdateResult * ProcessBatchUpdate(BatchUpdateSpec *updateSpec,
                                              MongoCollection *collection,
                                              bool isRetryableWrite,
                                              uint64 transactionId,
                                              bool useTransactionId);
static BatchUpdateResult * ProcessBatchUpdateCore(BatchUpdateSpec *updateSpec,
                                                  MongoCollection *collection,
                                                  bool isRetryableWrite,
                                                  uint64 transactionId);
static BatchUpdateResult * ProcessBatchUpdateUnsharded(BatchUpdateSpec *updateSpec,
                                                       MongoCollection *collection);
static void ProcessUpdate(UpdateSpec *updateSpec, MongoCollection *collection,
                         BatchUpdateResult *updateResult);
static UpdateOneResult UpdateAllMatchingDocuments(MongoCollection *collection,
                                                  pgbson *queryDocument,
                                                  pgbson *updateDocument,
                                                  bool isUpsert,
                                                  pgbson *arrayFilters,
                                                  pgbson *hint,
                                                  bson_value_t *variableSpec,
                                                  uint64 shardKeyValue,
                                                  bool bypassDocumentValidation,
                                                  bool isRetryableWrite,
                                                  uint64 transactionId);
static UpdateOneResult CallUpdateOne(MongoCollection *collection, pgbson *queryDocument,
                                    pgbson *updateDocument, bool isUpsert,
                                    pgbson *arrayFilters, pgbson *hint);
static UpdateOneResult UpdateOneInternal(MongoCollection *collection, pgbson *queryDocument,
                                        pgbson *updateDocument, bool isUpsert,
                                        pgbson *arrayFilters, pgbson *hint);
static UpdateOneResult UpdateOneInternalWithRetryRecord(MongoCollection *collection,
                                                       pgbson *queryDocument,
                                                       pgbson *updateDocument,
                                                       bool isUpsert,
                                                       pgbson *arrayFilters,
                                                       pgbson *hint);
static UpdateCandidateResult SelectUpdateCandidate(MongoCollection *collection,
                                                   pgbson *queryDocument,
                                                   pgbson *updateDocument,
                                                   pgbson *arrayFilters,
                                                   pgbson *hint,
                                                   uint64 shardKeyValue);
static void UpdateDocumentByTID(MongoCollection *collection, ItemPointer tid,
                               pgbson *updatedDocument);
static void DeleteDocumentByTID(MongoCollection *collection, ItemPointer tid);
static UpdateOneResult UpdateOneObjectId(MongoCollection *collection, pgbson *queryDocument,
                                        pgbson *updateDocument, bool isUpsert,
                                        pgbson *arrayFilters, pgbson *hint);
static pgbson * UpsertDocument(MongoCollection *collection, pgbson *queryDocument,
                              pgbson *updateDocument, pgbson *arrayFilters,
                              pgbson *hint, bson_value_t *variableSpec);
Datum
command_update_bulk(PG_FUNCTION_ARGS)
{
    pgbson *updateSpec = PG_GETARG_PGBSON(0);
    pgbsonsequence *updateSequence = PG_GETARG_PGBSONSEQUENCE(1);
    bson_iter_t updateCommandIter;
    PgbsonInitIterator(updateSpec, &updateCommandIter);
    BatchUpdateSpec *batchUpdateSpec = BuildBatchUpdateSpec(&updateCommandIter, updateSequence);
    MongoCollection *collection = GetMongoCollectionByName(batchUpdateSpec->collectionName,
                                                          AccessShareLock);
    if (collection == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_NAMESPACENOTFOUND),
                        errmsg("ns not found")));
    }
    bool isRetryableWrite = false;
    uint64 transactionId = 0;
    bool useTransactionId = false;
    BatchUpdateResult *updateResult = ProcessBatchUpdate(batchUpdateSpec, collection,
                                                         isRetryableWrite, transactionId,
                                                         useTransactionId);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    PgbsonWriterAppendDouble(&writer, "ok", 2, updateResult->ok);
    PgbsonWriterAppendInt64(&writer, "nMatched", 8, updateResult->rowsMatched);
    PgbsonWriterAppendInt64(&writer, "nModified", 9, updateResult->rowsModified);
    if (updateResult->upserted != NIL)
    {
        PgbsonWriterStartArray(&writer, "upserted", 8);
        ListCell *upsertCell;
        foreach(upsertCell, updateResult->upserted)
        {
            pgbson *upsertBson = (pgbson *) lfirst(upsertCell);
            PgbsonWriterAppendValue(&writer, "", 0, PgbsonGetBsonValue(upsertBson));
        }
        PgbsonWriterEndArray(&writer);
    }
    if (updateResult->writeErrors != NIL)
    {
        PgbsonWriterStartArray(&writer, "writeErrors", 11);
        ListCell *errorCell;
        foreach(errorCell, updateResult->writeErrors)
        {
            pgbson *errorBson = (pgbson *) lfirst(errorCell);
            PgbsonWriterAppendValue(&writer, "", 0, PgbsonGetBsonValue(errorBson));
        }
        PgbsonWriterEndArray(&writer);
    }
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
Datum
command_update(PG_FUNCTION_ARGS)
{
    pgbson *updateSpec = PG_GETARG_PGBSON(0);
    bson_iter_t updateCommandIter;
    PgbsonInitIterator(updateSpec, &updateCommandIter);
    BatchUpdateSpec *batchUpdateSpec = BuildBatchUpdateSpec(&updateCommandIter, NULL);
    MongoCollection *collection = GetMongoCollectionByName(batchUpdateSpec->collectionName,
                                                          AccessShareLock);
    if (collection == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_NAMESPACENOTFOUND),
                        errmsg("ns not found")));
    }
    bool isRetryableWrite = false;
    uint64 transactionId = 0;
    bool useTransactionId = false;
    BatchUpdateResult *updateResult = ProcessBatchUpdate(batchUpdateSpec, collection,
                                                         isRetryableWrite, transactionId,
                                                         useTransactionId);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    PgbsonWriterAppendDouble(&writer, "ok", 2, updateResult->ok);
    PgbsonWriterAppendInt64(&writer, "nMatched", 8, updateResult->rowsMatched);
    PgbsonWriterAppendInt64(&writer, "nModified", 9, updateResult->rowsModified);
    if (updateResult->upserted != NIL)
    {
        PgbsonWriterStartArray(&writer, "upserted", 8);
        ListCell *upsertCell;
        foreach(upsertCell, updateResult->upserted)
        {
            pgbson *upsertBson = (pgbson *) lfirst(upsertCell);
            PgbsonWriterAppendValue(&writer, "", 0, PgbsonGetBsonValue(upsertBson));
        }
        PgbsonWriterEndArray(&writer);
    }
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
```

## 第38页 共60页

### 文档删除操作 - delete.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "funcapi.h"
#include "miscadmin.h"
#include "access/xact.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "utils/builtins.h"
#include "io/bson_core.h"
#include "aggregation/bson_project.h"
#include "aggregation/bson_query.h"
#include "commands/commands_common.h"
#include "commands/delete.h"
#include "commands/parse_error.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "query/query_operator.h"
#include "infrastructure/documentdb_plan_cache.h"
#include "sharding/sharding.h"
#include "commands/retryable_writes.h"
#include "io/pgbsonsequence.h"
#include "utils/error_utils.h"
#include "utils/documentdb_errors.h"
#include "utils/feature_counter.h"
#include "utils/version_utils.h"
#include "utils/query_utils.h"
#include "api_hooks.h"
typedef struct
{
    DeleteOneParams deleteOneParams;
    int limit;
} DeletionSpec;
typedef struct
{
    char *collectionName;
    bson_value_t deletionValue;
    bool isOrdered;
    pgbsonsequence *deletionSequence;
    List *deletionsProcessed;
    bson_value_t variableSpec;
} BatchDeletionSpec;
typedef struct
{
    double ok;
    uint64 rowsDeleted;
    List *writeErrors;
} BatchDeletionResult;
extern bool UseLocalExecutionShardQueries;
extern bool EnableVariablesSupportForWriteCommands;
PG_FUNCTION_INFO_V1(command_delete);
PG_FUNCTION_INFO_V1(command_delete_one);
PG_FUNCTION_INFO_V1(command_delete_worker);
static BatchDeletionSpec * BuildBatchDeletionSpec(bson_iter_t *deleteCommandIter,
                                                  pgbsonsequence *deleteSequence);
static List * BuildDeletionSpecList(bson_iter_t *deleteArrayIter);
static List * BuildDeletionSpecListFromSequence(pgbsonsequence *deleteSequence,
                                                bson_value_t *variableSpec);
static DeletionSpec * BuildDeletionSpec(bson_iter_t *deleteSpecIter,
                                        bson_value_t *variableSpec);
static BatchDeletionResult * ProcessBatchDeletion(BatchDeletionSpec *deletionSpec,
                                                  MongoCollection *collection,
                                                  bool isRetryableWrite,
                                                  uint64 transactionId);
static BatchDeletionResult * ProcessBatchDeleteUnsharded(BatchDeletionSpec *deletionSpec,
                                                         MongoCollection *collection);
static void ProcessDeletion(DeletionSpec *deletionSpec, MongoCollection *collection,
                           BatchDeletionResult *deletionResult);
static DeleteOneResult DeleteAllMatchingDocuments(MongoCollection *collection,
                                                  pgbson *queryDocument,
                                                  uint64 shardKeyValue);
static DeleteOneResult DeleteOneInternal(MongoCollection *collection, pgbson *queryDocument,
                                        uint64 shardKeyValue, bool isRetryableWrite,
                                        uint64 transactionId);
static DeleteOneResult DeleteOneObjectId(MongoCollection *collection, pgbson *queryDocument,
                                        bool isRetryableWrite, uint64 transactionId,
                                        bool useTransactionId, bool *foundRetryRecord);
static DeleteOneResult DeleteOneInternalCore(MongoCollection *collection,
                                            pgbson *queryDocument,
                                            uint64 shardKeyValue);
static pgbson * CallDeleteWorker(MongoCollection *collection, pgbson *queryDocument,
                                 uint64 shardKeyValue, int limit,
                                 bool isRetryableWrite, uint64 transactionId);
static pgbson * DeserializeDeleteWorkerSpecForDeleteOne(pgbson *deleteWorkerSpec);
static pgbson * DeserializeWorkerDeleteResultForDeleteOne(pgbson *deleteWorkerResult);
static pgbson * DeserializeDeleteWorkerSpecForUnsharded(BatchDeletionSpec *deletionSpec,
                                                        MongoCollection *collection);
Datum
command_delete(PG_FUNCTION_ARGS)
{
    pgbson *deleteSpec = PG_GETARG_PGBSON(0);
    pgbsonsequence *deleteSequence = NULL;
    if (PG_NARGS() > 1 && !PG_ARGISNULL(1))
    {
        deleteSequence = PG_GETARG_PGBSONSEQUENCE(1);
    }
    bson_iter_t deleteCommandIter;
    PgbsonInitIterator(deleteSpec, &deleteCommandIter);
    BatchDeletionSpec *deletionSpec = BuildBatchDeletionSpec(&deleteCommandIter, deleteSequence);
    MongoCollection *collection = GetMongoCollectionByName(deletionSpec->collectionName,
                                                          AccessShareLock);
    if (collection == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_NAMESPACENOTFOUND),
                        errmsg("ns not found")));
    }
    bool isRetryableWrite = false;
    uint64 transactionId = 0;
    BatchDeletionResult *deletionResult = ProcessBatchDeletion(deletionSpec, collection,
                                                              isRetryableWrite, transactionId);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    PgbsonWriterAppendDouble(&writer, "ok", 2, deletionResult->ok);
    PgbsonWriterAppendInt64(&writer, "n", 1, deletionResult->rowsDeleted);
    if (deletionResult->writeErrors != NIL)
    {
        PgbsonWriterStartArray(&writer, "writeErrors", 11);
        ListCell *errorCell;
        foreach(errorCell, deletionResult->writeErrors)
        {
            pgbson *errorBson = (pgbson *) lfirst(errorCell);
            PgbsonWriterAppendValue(&writer, "", 0, PgbsonGetBsonValue(errorBson));
        }
        PgbsonWriterEndArray(&writer);
    }
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
```

## 第39页 共60页

### 查找并修改操作 - find_and_modify.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <storage/lockdefs.h>
#include <utils/builtins.h>
#include <funcapi.h>
#include "io/bson_core.h"
#include "update/bson_update.h"
#include "commands/commands_common.h"
#include "commands/delete.h"
#include "commands/insert.h"
#include "utils/documentdb_errors.h"
#include "commands/parse_error.h"
#include "commands/update.h"
#include "metadata/collection.h"
#include "query/query_operator.h"
#include "sharding/sharding.h"
#include "utils/feature_counter.h"
#include "schema_validation/schema_validation.h"
typedef struct
{
    char *collectionName;
    bson_value_t *query;
    bson_value_t *sort;
    bool remove;
    bson_value_t *update;
    bson_value_t *arrayFilters;
    bool returnNewDocument;
    bson_value_t *returnFields;
    bool upsert;
    bool bypassDocumentValidation;
} FindAndModifySpec;
typedef struct
{
    bool isUpdateCommand;
    struct
    {
        unsigned int n;
        bool updatedExisting;
        pgbson *upsertedObjectId;
    } lastErrorObject;
    pgbson *value;
    double ok;
} FindAndModifyResult;
PG_FUNCTION_INFO_V1(command_find_and_modify);
static FindAndModifyResult * ProcessFindAndModifySpec(FindAndModifySpec *spec,
                                                     MongoCollection *collection);
Datum
command_find_and_modify(PG_FUNCTION_ARGS)
{
    pgbson *findAndModifySpec = PG_GETARG_PGBSON(0);
    bson_iter_t findAndModifyIter;
    PgbsonInitIterator(findAndModifySpec, &findAndModifyIter);
    FindAndModifySpec *spec = ParseFindAndModifyMessage(&findAndModifyIter);
    MongoCollection *collection = GetMongoCollectionByName(spec->collectionName,
                                                          AccessShareLock);
    if (collection == NULL)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_NAMESPACENOTFOUND),
                        errmsg("ns not found")));
    }
    FindAndModifyResult *result = ProcessFindAndModifySpec(spec, collection);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    if (!result->isUpdateCommand)
    {
        PgbsonWriterStartDocument(&writer, "lastErrorObject", 15);
        PgbsonWriterAppendInt32(&writer, "n", 1, result->lastErrorObject.n);
        if (result->lastErrorObject.n > 0)
        {
            PgbsonWriterAppendBool(&writer, "updatedExisting", 15,
                                  result->lastErrorObject.updatedExisting);
            if (result->lastErrorObject.upsertedObjectId != NULL)
            {
                bson_value_t upsertedValue = PgbsonGetBsonValue(
                    result->lastErrorObject.upsertedObjectId);
                PgbsonWriterAppendValue(&writer, "upserted", 8, &upsertedValue);
            }
        }
        PgbsonWriterEndDocument(&writer);
    }
    if (result->value != NULL)
    {
        bson_value_t valueToWrite = PgbsonGetBsonValue(result->value);
        PgbsonWriterAppendValue(&writer, "value", 5, &valueToWrite);
    }
    else
    {
        PgbsonWriterAppendNull(&writer, "value", 5);
    }
    PgbsonWriterAppendDouble(&writer, "ok", 2, result->ok);
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
```

## 第40页 共60页

### 聚合管道核心处理 - bson_aggregation_pipeline.c

```c
#include <postgres.h>
#include <float.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <optimizer/optimizer.h>
#include <access/table.h>
#include <access/reloptions.h>
#include <utils/rel.h>
#include <catalog/namespace.h>
#include <optimizer/planner.h>
#include <nodes/nodes.h>
#include <nodes/makefuncs.h>
#include <nodes/nodeFuncs.h>
#include <parser/parser.h>
#include <parser/parse_agg.h>
#include <parser/parse_clause.h>
#include <parser/parse_param.h>
#include <parser/analyze.h>
#include <parser/parse_oper.h>
#include <utils/ruleutils.h>
#include <utils/builtins.h>
#include <catalog/pg_aggregate.h>
#include <catalog/pg_operator.h>
#include <catalog/pg_class.h>
#include <parser/parsetree.h>
#include <utils/array.h>
#include <utils/builtins.h>
#include <utils/lsyscache.h>
#include <utils/numeric.h>
#include <utils/lsyscache.h>
#include <utils/fmgroids.h>
#include <nodes/supportnodes.h>
#include <parser/parse_relation.h>
#include <parser/parse_func.h>
#include "io/bson_core.h"
#include "metadata/metadata_cache.h"
#include "query/query_operator.h"
#include "planner/documentdb_planner.h"
#include "aggregation/bson_aggregation_pipeline.h"
#include "aggregation/bson_aggregation_window_operators.h"
#include "commands/parse_error.h"
#include "commands/commands_common.h"
#include "commands/defrem.h"
#include "utils/feature_counter.h"
#include "utils/version_utils.h"
#include "aggregation/bson_query.h"
#include "aggregation/bson_aggregation_pipeline_private.h"
#include "aggregation/bson_bucket_auto.h"
#include "api_hooks.h"
#include "vector/vector_common.h"
#include "aggregation/bson_project.h"
#include "operators/bson_expression.h"
#include "operators/bson_expression_operators.h"
#include "operators/bson_expression_bucket_operator.h"
#include "geospatial/bson_geospatial_common.h"
#include "geospatial/bson_geospatial_geonear.h"
#include "aggregation/bson_densify.h"
#include "collation/collation.h"
#include "api_hooks.h"
extern bool EnableCursorsOnAggregationQueryRewrite;
extern bool EnableCollation;
extern bool DefaultInlineWriteOperations;
extern bool EnableSortbyIdPushDownToPrimaryKey;
extern int MaxAggregationStagesAllowed;
extern bool EnableIndexOrderbyPushdown;
extern int TdigestCompressionAccuracy;
typedef Query *(*MutateQueryForStageFunc)(const bson_value_t *existingValue,
                                          Query *query,
                                          AggregationPipelineBuildContext *context);
typedef void (*PipelineStagesPreCheckFunc)(const bson_value_t *existingValue,
                                          const AggregationPipelineBuildContext *context);
typedef bool (*RequiresPersistentCursorFunc)(const bson_value_t *existingValue);
typedef struct AggregationStageDefinition
{
    const char *stageName;
    MutateQueryForStageFunc mutateQueryFunc;
    PipelineStagesPreCheckFunc preCheckFunc;
    RequiresPersistentCursorFunc requiresPersistentCursorFunc;
    bool canInlineLookupPipeline;
    bool isChangeStreamCompatible;
    bool isViewCompatible;
    bool isReadOnlyStage;
    bool isWriteStage;
    bool isMetadataStage;
    bool requiresShardKeyInQuery;
    bool canPushToWorkers;
    bool canUseIndex;
    bool modifiesDocuments;
    bool requiresSort;
    bool canOptimizeSort;
    bool supportsCollation;
    bool supportsHint;
    bool supportsExplain;
    bool supportsReadConcern;
    bool supportsWriteConcern;
    bool supportsRetryableWrites;
    bool supportsTransactions;
    bool supportsArrayFilters;
    bool supportsUpsert;
    bool supportsMulti;
    bool supportsLimit;
    bool supportsSkip;
    bool supportsProjection;
    bool supportsSort;
    bool supportsCount;
    bool supportsDistinct;
    bool supportsMapReduce;
    bool supportsGeoNear;
    bool supportsText;
    bool supportsRegex;
    bool supportsWhere;
    bool supportsComment;
    bool supportsMaxTimeMS;
} AggregationStageDefinition;
PG_FUNCTION_INFO_V1(command_bson_aggregation_pipeline);
PG_FUNCTION_INFO_V1(command_api_collection);
PG_FUNCTION_INFO_V1(command_aggregation_support);
PG_FUNCTION_INFO_V1(documentdb_core_bson_to_bson);
static Query * AddCursorFunctionsToQuery(Query *query,
                                         AggregationPipelineBuildContext *context,
                                         bool addBatchSize);
static Query * AddQualifierForTailableQuery(Query *query,
                                            AggregationPipelineBuildContext *context,
                                            bool isTailable);
static void SetBatchSize(AggregationPipelineBuildContext *context);
static Query * AddShardKeyAndIdFilters(Query *query,
                                      AggregationPipelineBuildContext *context,
                                      bool addShardKeyFilter);
static Query * HandleAddFields(const bson_value_t *existingValue, Query *query,
                              AggregationPipelineBuildContext *context);
static Query * HandleBucket(const bson_value_t *existingValue, Query *query,
                           AggregationPipelineBuildContext *context);
static Query * HandleCount(const bson_value_t *existingValue, Query *query,
                          AggregationPipelineBuildContext *context);
static Query * HandleFill(const bson_value_t *existingValue, Query *query,
                         AggregationPipelineBuildContext *context);
static Query * HandleLimit(const bson_value_t *existingValue, Query *query,
                          AggregationPipelineBuildContext *context);
static Query * HandleProject(const bson_value_t *existingValue, Query *query,
                            AggregationPipelineBuildContext *context);
static Query * HandleProjectFind(const bson_value_t *existingValue, Query *query,
                                AggregationPipelineBuildContext *context,
                                bool isInclusionProjection);
static Query * HandleRedact(const bson_value_t *existingValue, Query *query,
                           AggregationPipelineBuildContext *context);
static Query * HandleReplaceRoot(const bson_value_t *existingValue, Query *query,
                                AggregationPipelineBuildContext *context);
static Query * HandleReplaceWith(const bson_value_t *existingValue, Query *query,
                                AggregationPipelineBuildContext *context);
static Query * HandleSample(const bson_value_t *existingValue, Query *query,
                           AggregationPipelineBuildContext *context);
static Query * HandleSkip(const bson_value_t *existingValue, Query *query,
                         AggregationPipelineBuildContext *context);
static Query * HandleSort(const bson_value_t *existingValue, Query *query,
                         AggregationPipelineBuildContext *context);
static Query * HandleSortByCount(const bson_value_t *existingValue, Query *query,
                                AggregationPipelineBuildContext *context);
static Query * HandleUnset(const bson_value_t *existingValue, Query *query,
                          AggregationPipelineBuildContext *context);
static Query * HandleUnwind(const bson_value_t *existingValue, Query *query,
                           AggregationPipelineBuildContext *context);
static Query * HandleDistinct(const bson_value_t *existingValue, Query *query,
                             AggregationPipelineBuildContext *context);
static Query * HandleGeoNear(const bson_value_t *existingValue, Query *query,
                            AggregationPipelineBuildContext *context);
static Query * HandleMatchAggregationStage(const bson_value_t *existingValue, Query *query,
                                          AggregationPipelineBuildContext *context);
```

## 第41页 共60页

### 集合元数据管理 - collection.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "access/xact.h"
#include "catalog/pg_attribute.h"
#include "commands/extension.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include "nodes/makefuncs.h"
#include "nodes/pg_list.h"
#include "parser/parse_func.h"
#include "storage/lmgr.h"
#include "funcapi.h"
#include "utils/builtins.h"
#include "utils/catcache.h"
#include "utils/guc.h"
#include "utils/inval.h"
#include "utils/lsyscache.h"
#include "utils/memutils.h"
#include "utils/syscache.h"
#include "utils/version_utils.h"
#include "metadata/collection.h"
#include "metadata/metadata_cache.h"
#include "utils/documentdb_errors.h"
#include "metadata/relation_utils.h"
#include "utils/query_utils.h"
#include "utils/guc_utils.h"
#include "metadata/metadata_guc.h"
#include "api_hooks.h"
#include "commands/parse_error.h"
#include "utils/feature_counter.h"
#define CREATE_COLLECTION_FUNC_NARGS 2
typedef struct NameToCollectionCacheEntry
{
    MongoCollectionName name;
    MongoCollection collection;
    bool isValid;
} NameToCollectionCacheEntry;
typedef struct RelationIdToCollectionCacheEntry
{
    Oid relationId;
    MongoCollection collection;
    bool isValid;
} RelationIdToCollectionCacheEntry;
static const char CharactersNotAllowedInDatabaseNames[7] = {
    '/', '\\', '.', ' ', '"', '$', '\0'
};
static const int CharactersNotAllowedInDatabaseNamesLength =
    sizeof(CharactersNotAllowedInDatabaseNames);
static const char CharactersNotAllowedInCollectionNames[2] = { '$', '\0' };
static const int CharactersNotAllowedInCollectionNamesLength =
    sizeof(CharactersNotAllowedInCollectionNames);
static const char *ValidSystemCollectionNames[5] = {
    "system.users", "system.js", "system.views", "system.profile", "system.dbSentinel"
};
static const int ValidSystemCollectionNamesLength = 5;
static const char *NonWritableSystemCollectionNames[4] = {
    "system.users", "system.js", "system.views", "system.profile"
};
static const int NonWritableSystemCollectionNamesLength = 4;
static HTAB *NameToCollectionHash = NULL;
static HTAB *RelationIdToCollectionHash = NULL;
static MongoCollection * GetMongoCollectionFromCatalogById(uint64 collectionId);
static MongoCollection * GetMongoCollectionFromCatalogByNameDatum(Datum databaseNameDatum,
                                                                  Datum collectionNameDatum);
static Oid GetRelationIdForCollectionTableName(const char *tableName);
static MongoCollection * GetMongoCollectionByNameDatumCore(Datum databaseNameDatum,
                                                           Datum collectionNameDatum,
                                                           LOCKMODE lockMode);
PG_FUNCTION_INFO_V1(command_collection_table);
PG_FUNCTION_INFO_V1(command_invalidate_collection_cache);
PG_FUNCTION_INFO_V1(command_get_collection_or_view);
PG_FUNCTION_INFO_V1(command_get_collection);
PG_FUNCTION_INFO_V1(command_get_next_collection_id);
PG_FUNCTION_INFO_V1(command_ensure_valid_db_coll);
void
InitializeCollectionsHash(void)
{
    HASHCTL info;
    memset(&info, 0, sizeof(info));
    info.keysize = sizeof(MongoCollectionName);
    info.entrysize = sizeof(NameToCollectionCacheEntry);
    info.hash = tag_hash;
    info.hcxt = CacheMemoryContext;
    NameToCollectionHash = hash_create("NameToCollectionHash",
                                      128, &info,
                                      HASH_ELEM | HASH_FUNCTION | HASH_CONTEXT);
    memset(&info, 0, sizeof(info));
    info.keysize = sizeof(Oid);
    info.entrysize = sizeof(RelationIdToCollectionCacheEntry);
    info.hash = oid_hash;
    info.hcxt = CacheMemoryContext;
    RelationIdToCollectionHash = hash_create("RelationIdToCollectionHash",
                                            128, &info,
                                            HASH_ELEM | HASH_FUNCTION | HASH_CONTEXT);
}
void
ResetCollectionsCache(void)
{
    if (NameToCollectionHash != NULL)
    {
        hash_destroy(NameToCollectionHash);
        NameToCollectionHash = NULL;
    }
    if (RelationIdToCollectionHash != NULL)
    {
        hash_destroy(RelationIdToCollectionHash);
        RelationIdToCollectionHash = NULL;
    }
}
void
InvalidateCollectionByRelationId(Oid relationId)
{
    if (RelationIdToCollectionHash == NULL)
    {
        return;
    }
    bool found = false;
    RelationIdToCollectionCacheEntry *entry =
        (RelationIdToCollectionCacheEntry *) hash_search(RelationIdToCollectionHash,
                                                         &relationId, HASH_FIND, &found);
    if (found)
    {
        entry->isValid = false;
        MongoCollectionName collectionName;
        collectionName.databaseName = entry->collection.databaseName;
        collectionName.collectionName = entry->collection.collectionName;
        NameToCollectionCacheEntry *nameEntry =
            (NameToCollectionCacheEntry *) hash_search(NameToCollectionHash,
                                                       &collectionName, HASH_FIND, &found);
        if (found)
        {
            nameEntry->isValid = false;
        }
    }
}
```

## 第42页 共60页

### 查询操作符处理 - query_operator.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <catalog/namespace.h>
#include <catalog/pg_collation.h>
#include <catalog/pg_operator.h>
#include <executor/executor.h>
#include <optimizer/optimizer.h>
#include <nodes/makefuncs.h>
#include <nodes/nodes.h>
#include <nodes/nodeFuncs.h>
#include <utils/builtins.h>
#include <utils/typcache.h>
#include <utils/lsyscache.h>
#include <utils/syscache.h>
#include <utils/timestamp.h>
#include <utils/array.h>
#include <parser/parse_coerce.h>
#include <parser/parsetree.h>
#include <parser/parse_clause.h>
#include <catalog/pg_type.h>
#include <funcapi.h>
#include <lib/stringinfo.h>
#include <metadata/metadata_cache.h>
#include <math.h>
#include <nodes/supportnodes.h>
#include "io/bson_core.h"
#include "query/bson_compare.h"
#include "aggregation/bson_query.h"
#include "types/decimal128.h"
#include "utils/documentdb_errors.h"
#include "commands/defrem.h"
#include "geospatial/bson_geospatial_common.h"
#include "geospatial/bson_geospatial_geonear.h"
#include "geospatial/bson_geospatial_shape_operators.h"
#include "metadata/collection.h"
#include "planner/documentdb_planner.h"
#include "query/query_operator.h"
#include "sharding/sharding.h"
#include "utils/rel.h"
#include "opclass/bson_text_gin.h"
#include "utils/feature_counter.h"
#include "vector/vector_common.h"
#include "vector/vector_utilities.h"
#include "types/pcre_regex.h"
#include "query/bson_dollar_operators.h"
#include "commands/commands_common.h"
#include "utils/version_utils.h"
#include "collation/collation.h"
#include "jsonschema/bson_json_schema_tree.h"
typedef struct ReplaceBsonQueryOperatorsContext
{
    Query *currentQuery;
    ParamListInfo boundParams;
    List *sortClauses;
    List *targetEntries;
} ReplaceBsonQueryOperatorsContext;
typedef struct IdFilterWalkerContext
{
    List *idQuals;
    bool hasIdFilter;
    bool hasNonIdFilter;
    bool hasComplexIdFilter;
    bool hasShardKeyFilter;
    bool hasNonShardKeyFilter;
    bool hasComplexShardKeyFilter;
    bool hasRangeShardKeyFilter;
    bool hasEqualityShardKeyFilter;
    bool hasInShardKeyFilter;
} IdFilterWalkerContext;
static Node * ReplaceBsonQueryOperatorsMutator(Node *node,
                                               ReplaceBsonQueryOperatorsContext *context);
static Expr * ExpandBsonQueryOperator(OpExpr *opExpr,
                                     ReplaceBsonQueryOperatorsContext *context,
                                     bool *hasIndexSupport);
static BoolExpr * CreateBoolExprFromLogicalExpression(bson_iter_t *logicalExpressionIter,
                                                     ReplaceBsonQueryOperatorsContext *context);
static List * CreateQualsFromLogicalExpressionArrayIterator(bson_iter_t *arrayIterator,
                                                           ReplaceBsonQueryOperatorsContext *context);
static OpExpr * CreateOpExprFromComparisonExpression(const bson_value_t *leftValue,
                                                    const bson_value_t *rightValue,
                                                    ReplaceBsonQueryOperatorsContext *context);
static Expr * CreateOpExprFromOperatorDocIterator(bson_iter_t *operatorDocIterator,
                                                 ReplaceBsonQueryOperatorsContext *context);
static Expr * CreateOpExprFromOperatorDocIteratorCore(bson_iter_t *operatorDocIterator,
                                                     ReplaceBsonQueryOperatorsContext *context,
                                                     bool *hasIndexSupport,
                                                     bool *isNegated);
static FuncExpr * CreateFuncExprForQueryOperator(const char *operatorName,
                                                const bson_value_t *leftValue,
                                                const bson_value_t *rightValue);
static Const * CreateConstFromBsonValue(const bson_value_t *value);
static Expr * CreateExprForDollarAll(const bson_value_t *leftValue,
                                    const bson_value_t *rightValue,
                                    ReplaceBsonQueryOperatorsContext *context);
static Expr * ExpandExprForDollarAll(const bson_value_t *leftValue,
                                    const bson_value_t *rightValue,
                                    ReplaceBsonQueryOperatorsContext *context);
static MongoCollection * GetCollectionReferencedByDocumentVar(Var *documentVar,
                                                             ReplaceBsonQueryOperatorsContext *context,
                                                             RangeTblEntry **rte);
static MongoCollection * GetCollectionForRTE(RangeTblEntry *rte);
static Expr * CreateExprForDollarRegex(const bson_value_t *leftValue,
                                      const bson_value_t *rightValue,
                                      ReplaceBsonQueryOperatorsContext *context);
static FuncExpr * CreateFuncExprForRegexOperator(const char *operatorName,
                                                const bson_value_t *leftValue,
                                                const bson_value_t *rightValue,
                                                const bson_value_t *optionsValue);
static Expr * CreateExprForDollarMod(const bson_value_t *leftValue,
                                    const bson_value_t *rightValue,
                                    ReplaceBsonQueryOperatorsContext *context);
static Expr * CreateExprForBitwiseQueryOperators(const char *operatorName,
                                                const bson_value_t *leftValue,
                                                const bson_value_t *rightValue);
static void SortAndWriteInt32BsonTypeArray(pgbson_writer *writer,
                                          const char *key, int keyLength,
                                          ArrayType *arrayType);
static List * CreateQualsFromQueryDocIteratorInternal(bson_iter_t *queryDocIterator,
                                                     ReplaceBsonQueryOperatorsContext *context);
static Expr * CreateQualForBsonValueExpressionCore(const bson_value_t *leftValue,
                                                   const bson_value_t *rightValue,
                                                   ReplaceBsonQueryOperatorsContext *context);
static bool TryProcessOrIntoDollarIn(bson_iter_t *logicalExpressionIter);
static bool TryOptimizeDollarOrExpr(bson_iter_t *logicalExpressionIter);
static Expr * ParseBsonValueForNearAndCreateOpExpr(const bson_value_t *leftValue,
                                                   const bson_value_t *rightValue,
                                                   ReplaceBsonQueryOperatorsContext *context);
```

## 第43页 共60页

### 索引元数据管理 - index.c

```c
#include <postgres.h>
#include <catalog/namespace.h>
#include <commands/sequence.h>
#include <executor/spi.h>
#include <utils/array.h>
#include <utils/builtins.h>
#include <utils/expandedrecord.h>
#include <utils/lsyscache.h>
#include <utils/syscache.h>
#include <nodes/makefuncs.h>
#include <catalog/namespace.h>
#include <miscadmin.h>
#include "api_hooks.h"
#include "io/bson_core.h"
#include "query/bson_compare.h"
#include "commands/create_indexes.h"
#include "metadata/index.h"
#include "metadata/metadata_cache.h"
#include "query/query_operator.h"
#include "utils/list_utils.h"
#include "metadata/relation_utils.h"
#include "utils/guc_utils.h"
#include "utils/query_utils.h"
#include "utils/documentdb_errors.h"
#include "metadata/metadata_guc.h"
#include "utils/version_utils.h"
#include "metadata/metadata_cache.h"
#include "utils/hashset_utils.h"
extern int MaxNumActiveUsersIndexBuilds;
extern int IndexBuildScheduleInSec;
static List * WriteIndexKeyForGetIndexes(pgbson_writer *writer, pgbson *keyDocument);
static pgbson * SerializeIndexSpec(const IndexSpec *spec, bool isGetIndexes,
                                   const char *namespaceName);
static IndexOptionsEquivalency IndexKeyDocumentEquivalent(pgbson *leftKey,
                                                          pgbson *rightKey);
static void DeleteCollectionIndexRecordCore(uint64 collectionId, int *indexId);
static ArrayType * ConvertUint64ListToArray(List *collectionIdArray);
static IndexOptionsEquivalency GetOptionsEquivalencyFromIndexOptions(
    HTAB *bsonElementHash,
    pgbson *leftIndexSpec,
    pgbson *rightIndexSpec);
PG_FUNCTION_INFO_V1(command_record_id_index);
PG_FUNCTION_INFO_V1(index_spec_options_are_equivalent);
PG_FUNCTION_INFO_V1(command_get_next_collection_index_id);
PG_FUNCTION_INFO_V1(index_spec_as_bson);
PG_FUNCTION_INFO_V1(get_index_spec_as_current_op_command);
Datum
command_record_id_index(PG_FUNCTION_ARGS)
{
    if (PG_ARGISNULL(0))
    {
        ereport(ERROR, (errmsg("collectionId cannot be NULL")));
    }
    uint64 collectionId = DatumGetUInt64(PG_GETARG_DATUM(0));
    IndexSpec idIndexSpec = MakeIndexSpecForBuiltinIdIndex();
    bool indexIsValid = true;
    RecordCollectionIndex(collectionId, &idIndexSpec, indexIsValid);
    PG_RETURN_VOID();
}
Datum
index_spec_options_are_equivalent(PG_FUNCTION_ARGS)
{
    if (PG_ARGISNULL(0) || PG_ARGISNULL(1))
    {
        PG_RETURN_BOOL(false);
    }
    pgbson *leftIndexSpec = PG_GETARG_PGBSON(0);
    pgbson *rightIndexSpec = PG_GETARG_PGBSON(1);
    IndexOptionsEquivalency equivalency = IndexSpecOptionsAreEquivalent(leftIndexSpec,
                                                                        rightIndexSpec);
    PG_RETURN_BOOL(equivalency == IndexOptionsEquivalency_Equivalent);
}
Datum
index_spec_as_bson(PG_FUNCTION_ARGS)
{
    if (PG_ARGISNULL(0))
    {
        ereport(ERROR, (errmsg("indexSpec cannot be NULL")));
    }
    IndexSpec *indexSpec = (IndexSpec *) PG_GETARG_POINTER(0);
    bool isGetIndexes = PG_GETARG_BOOL(1);
    text *namespaceNameText = PG_GETARG_TEXT_P(2);
    char *namespaceName = text_to_cstring(namespaceNameText);
    pgbson *result = SerializeIndexSpec(indexSpec, isGetIndexes, namespaceName);
    PG_RETURN_POINTER(result);
}
Datum
get_index_spec_as_current_op_command(PG_FUNCTION_ARGS)
{
    if (PG_ARGISNULL(0))
    {
        ereport(ERROR, (errmsg("indexSpec cannot be NULL")));
    }
    IndexSpec *indexSpec = (IndexSpec *) PG_GETARG_POINTER(0);
    text *namespaceNameText = PG_GETARG_TEXT_P(1);
    char *namespaceName = text_to_cstring(namespaceNameText);
    pgbson_writer writer;
    PgbsonWriterInit(&writer);
    WriteIndexSpecAsCurrentOpCommand(&writer, indexSpec, namespaceName);
    PG_RETURN_POINTER(PgbsonWriterGetPgbson(&writer));
}
```

## 第44页 共60页

### BSON比较操作符 - bson_dollar_operators.c

```c
#include <postgres.h>
#include <miscadmin.h>
#include <utils/array.h>
#include <utils/builtins.h>
#include <math.h>
#include "io/bson_core.h"
#include "aggregation/bson_query_common.h"
#include "io/bson_traversal.h"
#include "query/bson_compare.h"
#include "operators/bson_expression.h"
#include "query/bson_dollar_operators.h"
#include "utils/documentdb_errors.h"
#include "operators/bson_expr_eval.h"
#include "utils/fmgr_utils.h"
#include "utils/hashset_utils.h"
#include "opclass/bson_text_gin.h"
#include "types/decimal128.h"
#include "collation/collation.h"
#include "utils/version_utils.h"
#include "aggregation/bson_query.h"
typedef enum CustomOrderByOptions
{
    CustomOrderByOptions_Default = 0x0,
    CustomOrderByOptions_AllowOnlyDates = 0x1,
    CustomOrderByOptions_AllowOnlyNumbers = 0x2,
} CustomOrderByOptions;
typedef struct BsonDollarAllQueryState
{
    bool arrayHasOnlyNulls;
    int numElements;
    ExprEvalState **evalStateArray;
    PcreData **crePcreData;
    pgbsonelement filterElement;
    const char *collationString;
} BsonDollarAllQueryState;
typedef struct BsonDollarInQueryState
{
    pgbsonelement filterElement;
    List *regexList;
    HTAB *bsonValueHashSet;
    bool arrayHasNullValue;
    const char *collationString;
} BsonDollarInQueryState;
typedef struct TraverseOrderByValidateState
{
    CustomOrderByOptions orderByOptions;
    bool foundValue;
    bool foundValidValue;
    bool foundInvalidValue;
    const char *collationString;
} TraverseOrderByValidateState;
typedef struct TraverseElementValidateState
{
    bool foundValue;
    bool foundValidValue;
    bool foundInvalidValue;
} TraverseElementValidateState;
typedef struct TraverseInValidateState
{
    bool foundValue;
    bool foundValidValue;
    bool foundInvalidValue;
    BsonDollarInQueryState *queryState;
    bool isNinOperator;
    bool foundMatch;
    bool foundNullValue;
    bool foundUndefinedValue;
    bool foundRegexMatch;
    bool foundNonRegexMatch;
    bool foundArrayValue;
    bool foundNonArrayValue;
    bool foundObjectValue;
    bool foundNonObjectValue;
} TraverseInValidateState;
typedef struct TraverseAllValidateState
{
    bool foundValue;
    bool foundValidValue;
    bool foundInvalidValue;
    BsonDollarAllQueryState *queryState;
    bool foundMatch;
    bool foundNullValue;
    bool foundUndefinedValue;
    bool foundRegexMatch;
    bool foundNonRegexMatch;
    bool foundArrayValue;
    bool foundNonArrayValue;
    bool foundObjectValue;
    bool foundNonObjectValue;
    int numMatches;
    int numRequiredMatches;
} TraverseAllValidateState;
typedef struct TraverseRangeValidateState
{
    bool foundValue;
    bool foundValidValue;
    bool foundInvalidValue;
    pgbsonelement lowerBound;
    pgbsonelement upperBound;
} TraverseRangeValidateState;
typedef struct BsonDollarExprQueryState
{
    pgbsonelement filterElement;
    ExprEvalState *exprEvalState;
    bool isExpressionValid;
    bool isExpressionEvaluated;
    bool expressionResult;
    const char *collationString;
    MemoryContext exprContext;
    MemoryContext oldContext;
} BsonDollarExprQueryState;
```

## 第45页 共60页

### BSON文档更新操作 - bson_update.c

```c
#include "math.h"
#include "postgres.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "lib/stringinfo.h"
#include "utils/builtins.h"
#include "utils/timestamp.h"
#include "datatype/timestamp.h"
#include "funcapi.h"
#include "io/bson_core.h"
#include "query/bson_compare.h"
#include "aggregation/bson_project.h"
#include "utils/documentdb_errors.h"
#include "update/bson_update_common.h"
#include "update/bson_update.h"
#include "utils/fmgr_utils.h"
#include "aggregation/bson_query.h"
#include "commands/commands_common.h"
#include "api_hooks.h"
#include "api_hooks_def.h"
CreateBsonUpdateTracker_HookType create_update_tracker_hook = NULL;
BuildUpdateDescription_HookType build_update_description_hook = NULL;
int NumBsonDocumentsUpdated = 0;
typedef struct BsonUpdateMetadata
{
    UpdateType updateType;
    pgbson *sourceDocOnUpsert;
    union
    {
        struct AggregationPipelineUpdateState *aggregationState;
        const BsonIntermediatePathNode *operatorState;
    };
} BsonUpdateMetadata;
typedef struct
{
    BsonIntermediatePathNode *root;
    UpdateType updateType;
} QueryProjectionContext;
static void BuildBsonUpdateMetadata(BsonUpdateMetadata *metadata,
                                   const bson_value_t *updateSpec,
                                   const bson_value_t *querySpec, const
                                   bson_value_t *arrayFilters,
                                   bool buildSourceDocOnUpsert);
static pgbson * BsonUpdateDocumentCore(pgbson *sourceDocument, const
                                      bson_value_t *updateSpec,
                                      BsonUpdateMetadata *metadata);
static pgbson * ProcessReplaceDocument(pgbson *sourceDoc, const bson_value_t *updateSpec,
                                      bool isUpsert);
static pgbson * BuildBsonDocumentFromQuery(pgbson *sourceDoc, const
                                          bson_value_t *querySpec,
                                          UpdateType updateType);
static void ProcessQueryProjectionValue(void *context, const char *path, const
                                       bson_value_t *value);
static void
ThrowIdPathModifiedError(void)
{
    ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_IMMUTABLEFIELD),
                    errmsg("Performing an update on the path '_id' would modify the immutable field '_id'"),
                    errdetail_log("Performing an update on the path '_id' would modify the immutable field '_id'")));
}
static void
ValidateIdForUpdateTypeReplacement(pgbson *sourceDoc, const bson_value_t *updateSpec)
{
    if (updateSpec->value_type != BSON_TYPE_DOCUMENT)
    {
        return;
    }
    bson_iter_t sourceDocIter;
    PgbsonInitIterator(sourceDoc, &sourceDocIter);
    if (!bson_iter_find(&sourceDocIter, "_id"))
    {
        return;
    }
    bson_value_t sourceIdValue = *bson_iter_value(&sourceDocIter);
    bson_iter_t updateSpecIter;
    BsonValueInitIterator(updateSpec, &updateSpecIter);
    if (!bson_iter_find(&updateSpecIter, "_id"))
    {
        return;
    }
    bson_value_t updateIdValue = *bson_iter_value(&updateSpecIter);
    if (!BsonValueEquals(&sourceIdValue, &updateIdValue))
    {
        ThrowIdPathModifiedError();
    }
}
```

## 第46页 共60页

### 向量搜索工具函数 - vector_utilities.c

```c
#include <postgres.h>
#include <catalog/pg_operator.h>
#include <catalog/pg_type.h>
#include <nodes/makefuncs.h>
#include <utils/array.h>
#include <utils/builtins.h>
#include <utils/rel.h>
#include <utils/syscache.h>
#include <commands/defrem.h>
#include <catalog/pg_collation.h>
#include <utils/lsyscache.h>
#include "api_hooks.h"
#include "io/bson_core.h"
#include "utils/documentdb_errors.h"
#include "metadata/metadata_cache.h"
#include "vector/bson_extract_vector.h"
#include "vector/vector_common.h"
#include "vector/vector_configs.h"
#include "vector/vector_planner.h"
#include "vector/vector_utilities.h"
#include "vector/vector_spec.h"
#include "utils/error_utils.h"
static Expr * GenerateVectorExractionExprFromQueryWithCast(Node *vectorQuerySpecNode,
                                                           FuncExpr *vectorCastFunc);
static VectorIndexDistanceMetric GetDistanceMetricFromOpId(Oid similaritySearchOpId);
static VectorIndexDistanceMetric GetDistanceMetricFromOpName(const
                                                             char *similaritySearchOpName);
static bool IsHalfVectorCastFunctionCore(FuncExpr *vectorCastFunc,
                                         bool logWarning);
double
EvaluateMetaSearchScore(pgbson *document)
{
    const char *metaScorePathName =
        VECTOR_METADATA_FIELD_NAME "." VECTOR_METADATA_SCORE_FIELD_NAME;
    bson_iter_t documentIterator;
    if (PgbsonInitIteratorAtPath(document, metaScorePathName, &documentIterator))
    {
        return BsonValueAsDouble(bson_iter_value(&documentIterator));
    }
    else
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_LOCATION40218),
                        errmsg(
                            "query requires search score metadata, but it is not available")));
    }
}
bool
IsHalfVectorCastFunction(FuncExpr *vectorCastFunc)
{
    return IsHalfVectorCastFunctionCore(vectorCastFunc, false);
}
bool
IsMatchingVectorIndex(VectorIndexSpec *vectorIndexSpec, Node *vectorQuerySpecNode,
                      FuncExpr *vectorCastFunc, Oid similaritySearchOpId)
{
    if (vectorIndexSpec == NULL)
    {
        return false;
    }
    if (vectorQuerySpecNode == NULL)
    {
        return false;
    }
    if (similaritySearchOpId == InvalidOid)
    {
        return false;
    }
    VectorIndexDistanceMetric distanceMetric = GetDistanceMetricFromOpId(
        similaritySearchOpId);
    if (distanceMetric == VectorIndexDistanceMetric_Invalid)
    {
        return false;
    }
    if (vectorIndexSpec->distanceMetric != distanceMetric)
    {
        return false;
    }
    if (vectorCastFunc != NULL)
    {
        if (IsHalfVectorCastFunctionCore(vectorCastFunc, true))
        {
            if (vectorIndexSpec->vectorType != VectorIndexVectorType_Float16)
            {
                return false;
            }
        }
        else
        {
            if (vectorIndexSpec->vectorType != VectorIndexVectorType_Float32)
            {
                return false;
            }
        }
    }
    else
    {
        if (vectorIndexSpec->vectorType != VectorIndexVectorType_Float32)
        {
            return false;
        }
    }
    return true;
}
```

## 第47页 共60页

### 地理空间处理 - bson_geospatial_common.c

```c
#include "postgres.h"
#include "fmgr.h"
#include "math.h"
#include "utils/builtins.h"
#include "utils/documentdb_errors.h"
#include "geospatial/bson_geojson_utils.h"
#include "geospatial/bson_geospatial_common.h"
#include "geospatial/bson_geospatial_private.h"
#include "utils/list_utils.h"
#include "io/bson_traversal.h"
#define IsIndexValidation(s) (s->validationLevel == GeospatialValidationLevel_Index)
#define IsBloomValidation(s) (s->validationLevel == GeospatialValidationLevel_BloomFilter)
#define IsRuntimeValidation(s) (s->validationLevel == GeospatialValidationLevel_Runtime)
#define IsIndexMultiKey(s) (IsIndexValidation(s) && s->isMultiKeyContext == true)
typedef enum PointProcessType
{
    PointProcessType_Invalid = 0,
    PointProcessType_Empty,
    PointProcessType_Valid,
} PointProcessType;
static bool LegacyPointVisitTopLevelField(pgbsonelement *element, const
                                          StringView *filterPath,
                                          void *state);
static bool GeographyVisitTopLevelField(pgbsonelement *element, const
                                        StringView *filterPath,
                                        void *state);
static bool GeographyValidateTopLevelField(pgbsonelement *element, const
                                           StringView *filterPath,
                                           void *state);
static bool ContinueProcessIntermediateArray(void *state, const
                                             bson_value_t *value);
static bool BsonValueAddLegacyPointDatum(const bson_value_t *value,
                                         ProcessCommonGeospatialState *state,
                                         bool *isNull);
static bool BsonValueParseAsLegacyPoint2d(const bson_value_t *value,
                                          ProcessCommonGeospatialState *state);
static const char * _2dsphereIndexErrorPrefix(const pgbson *document);
static const char * _2dsphereIndexErrorHintPrefix(const pgbson *document);
static const char * _2dIndexNoPrefix(const pgbson *document);
static Datum BsonExtractGeospatialInternal(const pgbson *document,
                                           const StringView *pathView,
                                           GeospatialType type,
                                           GeospatialValidationLevel level,
                                           WKBGeometryType collectType,
                                           GeospatialErrorContext *errCtxt);
static void SetQueryMatcherResult(ProcessCommonGeospatialState *state);
static const TraverseBsonExecutionFuncs ProcessLegacyCoordinates = {
    .ContinueProcessIntermediateArray = ContinueProcessIntermediateArray,
    .SetTraverseResult = NULL,
    .VisitArrayField = NULL,
    .VisitTopLevelField = LegacyPointVisitTopLevelField,
    .SetIntermediateArrayIndex = NULL,
    .HandleIntermediateArrayPathNotFound = NULL,
    .SetIntermediateArrayStartEnd = NULL,
};
static const TraverseBsonExecutionFuncs ProcessGeographyCoordinates = {
    .ContinueProcessIntermediateArray = ContinueProcessIntermediateArray,
    .SetTraverseResult = NULL,
    .VisitArrayField = NULL,
    .VisitTopLevelField = GeographyVisitTopLevelField,
    .SetIntermediateArrayIndex = NULL,
    .HandleIntermediateArrayPathNotFound = NULL,
    .SetIntermediateArrayStartEnd = NULL,
};
static const TraverseBsonExecutionFuncs ValidateGeographyCoordinates = {
    .ContinueProcessIntermediateArray = ContinueProcessIntermediateArray,
    .SetTraverseResult = NULL,
    .VisitArrayField = NULL,
    .VisitTopLevelField = GeographyValidateTopLevelField,
    .SetIntermediateArrayIndex = NULL,
    .HandleIntermediateArrayPathNotFound = NULL,
    .SetIntermediateArrayStartEnd = NULL,
};
void
UpdateStateAndRunMatcherIfValidPointFound(ProcessCommonGeospatialState *state)
{
    if (state->foundValidPoint)
    {
        SetQueryMatcherResult(state);
    }
    else
    {
        state->foundValidPoint = false;
        state->foundInvalidPoint = false;
        state->foundEmptyPoint = false;
    }
}
```

## 第48页 共60页

### BSON投影操作 - bson_project.c

```c
#include <postgres.h>
#include <miscadmin.h>
#include <fmgr.h>
#include <executor/executor.h>
#include <utils/builtins.h>
#include <utils/typcache.h>
#include <utils/lsyscache.h>
#include <utils/syscache.h>
#include <utils/timestamp.h>
#include <utils/array.h>
#include <utils/float.h>
#include <parser/parse_coerce.h>
#include <catalog/pg_type.h>
#include <funcapi.h>
#include <lib/stringinfo.h>
#include "aggregation/bson_project.h"
#include "types/decimal128.h"
#include "aggregation/bson_positional_query.h"
#include "aggregation/bson_tree_write.h"
#include "geospatial/bson_geospatial_geonear.h"
#include "query/bson_compare.h"
#include "utils/documentdb_errors.h"
#include "metadata/metadata_cache.h"
#include "operators/bson_expression.h"
#include "operators/bson_expr_eval.h"
#include "aggregation/bson_project_operator.h"
#include "utils/fmgr_utils.h"
#include "commands/commands_common.h"
#include "collation/collation.h"
const char COLLISION_ERR_MSG[75] =
    "Invalid specification for aggregation stage:: Path collision detected.";
typedef struct BsonProjectionQueryState
{
    const BsonIntermediatePathNode *root;
    ExpressionVariableContext *variableContext;
    bool hasInclusion;
    bool hasExclusion;
    bool projectNonMatchingFields;
    uint32_t endTotalProjections;
    BsonProjectDocumentFunctions projectDocumentFuncs;
} BsonProjectionQueryState;
typedef struct BsonReplaceRootRedactState
{
    AggregationExpressionData *expressionData;
    ExpressionVariableContext *variableContext;
} BsonReplaceRootRedactState;
static void AdjustPathProjectionsForId(BsonIntermediatePathNode *root);
static void ProjectCurrentIteratorFieldToWriter(pgbson_writer *writer,
                                               bson_iter_t *sourceIterator,
                                               const BsonIntermediatePathNode *currentNode,
                                               const BsonProjectionQueryState *queryState,
                                               const char *currentPath,
                                               uint32_t currentPathLength,
                                               bool isTopLevel);
static void HandleUnresolvedFields(pgbson_writer *writer,
                                 const BsonIntermediatePathNode *currentNode,
                                 const BsonProjectionQueryState *queryState,
                                 const char *currentPath);
static void TraverseArrayAndAppendToWriter(pgbson_writer *writer,
                                         const bson_value_t *arrayValue,
                                         const BsonIntermediatePathNode *currentNode,
                                         const BsonProjectionQueryState *queryState,
                                         const char *currentPath);
static void ProjectCurrentArrayIterToWriter(pgbson_writer *writer,
                                           bson_iter_t *arrayIterator,
                                           const BsonIntermediatePathNode *currentNode,
                                           const BsonProjectionQueryState *queryState,
                                           const char *currentPath,
                                           uint32_t currentPathLength);
static void TraverseDocumentAndWriteLookupIndexCondition(pgbson_writer *writer,
                                                       const bson_value_t *documentValue,
                                                       const char *localField);
static Expr * BsonLookUpGetFilterExpression(const bson_value_t *localFieldValue,
                                           const char *foreignField);
static pgbson * BsonLookUpProject(pgbson *document, const char *localField);
static void PopulateReplaceRootExpressionDataFromSpec(BsonReplaceRootRedactState *state,
                                                     const bson_value_t *spec);
static BsonReplaceRootRedactState * BuildRedactState(const bson_value_t *spec,
                                                    ExpressionVariableContext *variableContext);
static BsonProjectionQueryState * BuildBsonPathTreeForDollarProject(const bson_value_t *spec);
static BsonProjectionQueryState * BuildBsonPathTreeForDollarAddFields(const bson_value_t *spec,
                                                                      ExpressionVariableContext *variableContext,
                                                                      bool isSet,
                                                                      bool isUnset);
static BsonProjectionQueryState * BuildBsonPathTreeForDollarUnset(const bson_value_t *spec,
                                                                  ExpressionVariableContext *variableContext);
static BsonProjectionQueryState * BuildBsonPathTreeForDollarProjectFind(const bson_value_t *spec);
static BsonProjectionQueryState * BuildBsonPathTreeForDollarProjectCore(const bson_value_t *spec,
                                                                        ExpressionVariableContext *variableContext,
                                                                        bool isAddFields);
static void PostProcessParseProjectNode(BsonIntermediatePathNode *node,
                                       bool hasInclusion,
                                       bool hasExclusion);
static pgbson * ProjectGeonearDocument(pgbson *document, const char *distanceField);
static pgbson * EvaluateRedactDocument(pgbson *document,
                                      BsonReplaceRootRedactState *state);
static pgbson * EvaluateRedactArray(pgbson *document,
                                   BsonReplaceRootRedactState *state);
static pgbson * MergeDocumentWithArrayOverride(pgbson *sourceDocument,
                                              pgbson *overrideDocument,
                                              const char *arrayPath);
```

## 第49页 共60页

### JSON模式验证 - bson_json_schema_validator.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <funcapi.h>
#include <miscadmin.h>
#include "io/bson_core.h"
#include "query/bson_compare.h"
#include "jsonschema/bson_json_schema_tree.h"
#include "utils/documentdb_errors.h"
#include "metadata/metadata_cache.h"
#include "utils/fmgr_utils.h"
#include "utils/hashset_utils.h"
typedef struct BsonKeyValuePair
{
    const char *key;
    bson_value_t *value;
    List *subDocKvList;
} BsonKeyValuePair;
static bool ValidateBsonValueAgainstSchemaTree(const bson_value_t *value,
                                               const SchemaNode *node);
static bool ValidateBsonValueCommon(const bson_value_t *value,
                                    const SchemaNode *node);
static bool ValidateBsonValueObject(const bson_value_t *value,
                                    const SchemaNode *node);
static bool ValidateBsonValueString(const bson_value_t *value,
                                    const SchemaNode *node);
static bool ValidateBsonValueNumeric(const bson_value_t *value,
                                     const SchemaNode *node);
static bool ValidateBsonValueArray(const bson_value_t *value,
                                   const SchemaNode *node);
static BsonTypeFlags GetBsonValueTypeFlag(bson_type_t type);
static void FreeListOfDocKvLists(List *list);
static void FreeDocKvList(List *list);
static int CompareKeysInBsonKeyValuePairs(const ListCell *cellA, const ListCell *cellB);
static int CompareBsonDocKvLists(List *docKvListA, List *docKvListB,
                                 bool *isComparisonValid);
static int CompareBsonKvPairs(BsonKeyValuePair *pairA, BsonKeyValuePair *pairB,
                              bool *isComparisonValid);
static List * GetSortedListOfKeyValuePairs(const bson_value_t *value);
static bool IsBsonArrayUnique(const bson_value_t *value, bool ignoreKeyOrderInObject);
PG_FUNCTION_INFO_V1(bson_dollar_json_schema);
Datum
bson_dollar_json_schema(PG_FUNCTION_ARGS)
{
    pgbson *document = PG_GETARG_PGBSON(0);
    pgbson *schema = PG_GETARG_PGBSON(1);
    pgbsonelement element;
    bson_iter_t schemaIter;
    PgbsonToSinglePgbsonElement(schema, &element);
    if (element.bsonValue.value_type != BSON_TYPE_DOCUMENT)
    {
        ereport(ERROR,
                (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                 errmsg("$jsonSchema must be an object")));
    }
    BsonValueInitIterator(&(element.bsonValue), &schemaIter);
    const SchemaTreeState *treeState = NULL;
    SchemaTreeState localTreeState = { 0 };
    SetCachedFunctionState(
        treeState,
        SchemaTreeState,
        localTreeState,
        BuildSchemaTreeFromIterator(&schemaIter, &localTreeState));
    pgbsonelement documentElement;
    PgbsonToSinglePgbsonElement(document, &documentElement);
    bool isValid = ValidateBsonValueAgainstSchemaTree(&documentElement.bsonValue,
                                                      treeState->rootNode);
    PG_RETURN_BOOL(isValid);
}
bool
ValidateBsonValueAgainstSchemaTree(const bson_value_t *value,
                                   const SchemaNode *node)
{
    if (node == NULL)
    {
        return true;
    }
    if (node->allOfNodes != NIL)
    {
        ListCell *cell;
        foreach(cell, node->allOfNodes)
        {
            SchemaNode *allOfNode = (SchemaNode *) lfirst(cell);
            if (!ValidateBsonValueAgainstSchemaTree(value, allOfNode))
            {
                return false;
            }
        }
    }
    if (node->anyOfNodes != NIL)
    {
        bool anyOfMatched = false;
        ListCell *cell;
        foreach(cell, node->anyOfNodes)
        {
            SchemaNode *anyOfNode = (SchemaNode *) lfirst(cell);
            if (ValidateBsonValueAgainstSchemaTree(value, anyOfNode))
            {
                anyOfMatched = true;
                break;
            }
        }
        if (!anyOfMatched)
        {
            return false;
        }
    }
    return ValidateBsonValueCommon(value, node);
}
```

## 第50页 共60页

### 文本搜索索引 - bson_text_gin.c

```c
#include <postgres.h>
#include <miscadmin.h>
#include <fmgr.h>
#include <string.h>
#include <utils/builtins.h>
#include <access/reloptions.h>
#include <tsearch/ts_utils.h>
#include <tsearch/ts_type.h>
#include <tsearch/ts_cache.h>
#include <catalog/namespace.h>
#include <utils/array.h>
#include <nodes/makefuncs.h>
#include "io/bson_core.h"
#include "opclass/bson_gin_common.h"
#include "opclass/bson_gin_index_mgmt.h"
#include "opclass/bson_gin_private.h"
#include "utils/documentdb_errors.h"
#include "opclass/bson_text_gin.h"
#include "metadata/metadata_cache.h"
#include "opclass/bson_index_support.h"
extern QueryTextIndexData *QueryTextData;
typedef struct
{
    const char *mongoLanguageName;
    const char *postgresLanguageName;
} MongoLanguageExpression;
typedef struct TextQueryEvalData
{
    BsonGinTextPathOptions *indexOptions;
    TSQuery queryData;
} TextQueryEvalData;
static QTNode * RewriteQueryTree(QTNode *node, bool *rewrote);
static IndexTraverseOption GetTextIndexTraverseOption(void *contextOptions,
                                                      const char *currentPath, uint32_t
                                                      currentPathLength,
                                                      bson_type_t bsonType);
static Oid ExtractTsConfigFromLanguage(const StringView *stringView,
                                       bool isCreateIndex);
static void BsonValidateAndExtractTextQuery(const bson_value_t *queryValue,
                                             bson_value_t *searchValue,
                                             Oid *languageOid,
                                             bson_value_t *caseSensitive,
                                             bson_value_t *diacriticSensitive);
static Datum BsonTextGenerateTSQueryCore(const bson_value_t *queryValue,
                                         bytea *indexOptions, Oid tsConfigOid);
static void ValidateDefaultLanguageSpec(const char *defaultLanguage);
static Size FillDefaultLanguageSpec(const char *defaultLanguage, void *buffer);
static void ValidateWeightsSpec(const char *weightsSpec);
static Size FillWeightsSpec(const char *weightsSpec, void *buffer);
static TSVector GenerateTsVectorWithOptions(pgbson *doc,
                                            BsonGinTextPathOptions *options);
inline static Oid
GetDefaultLanguage(BsonGinTextPathOptions *options)
{
    const char *languageOption = GET_STRING_RELOPTION(options, defaultLanguage);
    if (languageOption != NULL)
    {
        Oid *languageOid = (Oid *) languageOption;
        if (*languageOid != InvalidOid)
        {
            return *languageOid;
        }
    }
    return get_current_ts_config();
}
Datum
rum_bson_single_path_extract_tsvector(PG_FUNCTION_ARGS)
{
    pgbson *document = PG_GETARG_PGBSON(0);
    bytea *indexOptions = PG_GETARG_BYTEA_P(1);
    BsonGinTextPathOptions *options = (BsonGinTextPathOptions *) VARDATA(indexOptions);
    TSVector result = GenerateTsVectorWithOptions(document, options);
    if (result == NULL)
    {
        PG_RETURN_NULL();
    }
    PG_RETURN_TSVECTOR(result);
}
Datum
command_bson_query_to_tsquery(PG_FUNCTION_ARGS)
{
    pgbson *queryBson = PG_GETARG_PGBSON(0);
    bytea *indexOptions = PG_GETARG_BYTEA_P(1);
    pgbsonelement queryElement;
    PgbsonToSinglePgbsonElement(queryBson, &queryElement);
    Datum result = BsonTextGenerateTSQueryCore(&queryElement.bsonValue,
                                               indexOptions, InvalidOid);
    PG_RETURN_DATUM(result);
}
```

## 第51页 共60页

### Decimal128数据类型 - decimal128.c

```c
#include "types/decimal128.h"
#include <bid_conf.h>
#include <bid_functions.h>
#include <math.h>
#include <lib/stringinfo.h>
#include "utils/documentdb_errors.h"
#if BID_BIG_ENDIAN
#define BID_HIGH_BITS 0
#define BID_LOW_BITS 1
#else
#define BID_HIGH_BITS 1
#define BID_LOW_BITS 0
#endif
#define BID128_EXP_BIAS 6176ull
#define INFINITY_MASK64 0x7800000000000000ull
#define SINFINITY_MASK64 0xf800000000000000ull
#define NAN_MASK64 0x7c00000000000000ull
#define BID128_EXP_BITS_OFFSET 49
typedef enum Decimal128RoundingMode
{
    Decimal128RoundingMode_NearestEven = 0,
    Decimal128RoundingMode_Downward = 1,
    Decimal128RoundingMode_Upward = 2,
    Decimal128RoundingMode_TowardZero = 3,
    Decimal128RoundingMode_NearestAway = 4,
    Decimal128RoundingMode_Default = Decimal128RoundingMode_NearestEven
} Decimal128RoundingMode;
typedef enum Decimal128MathOperation
{
    Decimal128MathOperation_Add = 0,
    Decimal128MathOperation_Subtract = 1,
    Decimal128MathOperation_Multiply = 2,
    Decimal128MathOperation_Divide = 3,
    Decimal128MathOperation_Mod = 4,
    Decimal128MathOperation_Ceil = 5,
    Decimal128MathOperation_Floor = 6,
    Decimal128MathOperation_Exp = 7,
    Decimal128MathOperation_Sqrt = 8,
    Decimal128MathOperation_Abs = 9,
    Decimal128MathOperation_Log10 = 10,
    Decimal128MathOperation_NaturalLogarithm = 11,
    Decimal128MathOperation_Log = 12,
    Decimal128MathOperation_Pow = 13,
    Decimal128MathOperation_Round = 14,
    Decimal128MathOperation_Trunc = 15,
    Decimal128MathOperation_Sin = 16,
    Decimal128MathOperation_Cos = 17,
    Decimal128MathOperation_Tan = 18,
    Decimal128MathOperation_Sinh = 19,
    Decimal128MathOperation_Cosh = 20,
    Decimal128MathOperation_Tanh = 21,
    Decimal128MathOperation_Asin = 22,
    Decimal128MathOperation_Acos = 23,
    Decimal128MathOperation_Atan = 24,
    Decimal128MathOperation_Asinh = 25,
    Decimal128MathOperation_Acosh = 26,
    Decimal128MathOperation_Atanh = 27,
    Decimal128MathOperation_Atan2 = 28
} Decimal128MathOperation;
int32
GetBsonDecimal128AsInt32(bson_decimal128_t decimal128)
{
    BIDUINT128 bidValue = GetBIDUINT128FromBsonValue(&decimal128);
    _IDEC_flags flags = ALL_EXCEPTION_FLAG_CLEAR;
    int32 result = __bid128_to_int32_int(bidValue, &flags);
    if (flags & BID_INVALID_EXCEPTION)
    {
        ThrowConversionFailureError("int32");
    }
    return result;
}
int64
GetBsonDecimal128AsInt64(bson_decimal128_t decimal128)
{
    BIDUINT128 bidValue = GetBIDUINT128FromBsonValue(&decimal128);
    _IDEC_flags flags = ALL_EXCEPTION_FLAG_CLEAR;
    int64 result = __bid128_to_int64_int(bidValue, &flags);
    if (flags & BID_INVALID_EXCEPTION)
    {
        ThrowConversionFailureError("int64");
    }
    return result;
}
```

## 第52页 共60页

### 国际化排序规则 - collation.c

```c
#include <postgres.h>
#include <unicode/ures.h>
#include <unicode/uloc.h>
#include <utils/hsearch.h>
#include <utils/memutils.h>
#include <unicode/umachine.h>
#include <utils/pg_locale.h>
#include <common/hashfn.h>
#include "io/bson_core.h"
#include "lib/stringinfo.h"
#include "utils/documentdb_errors.h"
#include "collation/collation.h"
#define ALPHABET_SIZE 26
#define DEFAULT_ICU_COLLATION_SORT_KEY_LENGTH 512
typedef struct
{
    unsigned long collationKey;
    UCollator *collator;
} ucollator_cache_entry;
char supported_locale_codes[ALPHABET_SIZE][ALPHABET_SIZE] = {
    { ' ', ' ', ' ', ' ', ' ', 't', ' ', ' ', ' ', ' ', ' ', ' ', 't', ' ', ' ',
      ' ', ' ', 'C', 't', ' ', ' ', ' ', ' ', ' ', ' ', 'S' },
    { ' ', ' ', ' ', ' ', 't', ' ', 't', ' ', ' ', ' ', ' ', ' ', ' ', 'T', 't',
      ' ', ' ', ' ', 'G', ' ', ' ', ' ', ' ', ' ', ' ', ' ' },
    { 'S', ' ', ' ', ' ', ' ', ' ', ' ', 'R', ' ', ' ', ' ', ' ', ' ', ' ', ' ',
      ' ', ' ', ' ', 'S', ' ', ' ', ' ', ' ', ' ', 't', ' ' },
    { 'S', ' ', ' ', ' ', 'D', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ',
      ' ', ' ', ' ', 'B', ' ', ' ', ' ', ' ', ' ', ' ', 't' }
};
pgbson *
ParseAndGetCollationString(const bson_value_t *collationValue)
{
    if (collationValue->value_type != BSON_TYPE_DOCUMENT)
    {
        ereport(ERROR, (errcode(ERRCODE_DOCUMENTDB_TYPEMISMATCH),
                        errmsg("collation must be a document")));
    }
    bson_iter_t collationIterator;
    BsonValueInitIterator(collationValue, &collationIterator);
    pgbson_writer collationWriter;
    PgbsonWriterInit(&collationWriter);
    while (bson_iter_next(&collationIterator))
    {
        const char *key = bson_iter_key(&collationIterator);
        const bson_value_t *value = bson_iter_value(&collationIterator);
        CheckCollationInputParamType(key, value);
        if (strcmp(key, "locale") == 0)
        {
            if (value->value_type == BSON_TYPE_UTF8)
            {
                StringView localeStringView = CreateStringViewFromString(value->value.v_utf8.str);
                if (!CheckIfValidLocale(&localeStringView))
                {
                    ThrowInvalidLocaleError(value->value.v_utf8.str);
                }
                char *icuLocaleString = GenerateICULocaleAndExtractCollationOption(&localeStringView);
                PgbsonWriterAppendUtf8(&collationWriter, key, icuLocaleString);
                pfree(icuLocaleString);
            }
        }
        else
        {
            PgbsonWriterAppendValue(&collationWriter, key, value);
        }
    }
    return PgbsonWriterGetPgbson(&collationWriter);
}
```

## 第53页 共60页

### BSON表达式求值 - bson_expr_eval.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <miscadmin.h>
#include <utils/builtins.h>
#include <nodes/execnodes.h>
#include <executor/executor.h>
#include "operators/bson_expr_eval.h"
#include "query/query_operator.h"
#include "utils/documentdb_errors.h"
#include "metadata/metadata_cache.h"
static Datum ExpressionEval(ExprEvalState *exprEvalState,
                           const pgbsonelement *element);
static ExprEvalState * CreateEvalStateFromExpr(Expr *expression, Oid attributeOid);
static Datum ExpressionEvalForBson(ExprEvalState *exprEvalState,
                                  const pgbson *bson);
PG_FUNCTION_INFO_V1(command_evaluate_query_expression);
PG_FUNCTION_INFO_V1(command_evaluate_expression_get_first_match);
Datum
command_evaluate_query_expression(PG_FUNCTION_ARGS)
{
    pgbson *expression = PG_GETARG_PGBSON(0);
    pgbson *value = PG_GETARG_PGBSON(1);
    pgbsonelement valueElement;
    PgbsonToSinglePgbsonElement(value, &valueElement);
    bson_value_t expressionValue = ConvertPgbsonToBsonValue(expression);
    ExprEvalState *evalState = GetExpressionEvalState(&expressionValue,
                                                     fcinfo->flinfo->fn_mcxt);
    Datum result = ExpressionEval(evalState, &valueElement);
    PG_RETURN_BOOL(DatumGetBool(result));
}
Datum
command_evaluate_expression_get_first_match(PG_FUNCTION_ARGS)
{
    pgbson *expression = PG_GETARG_PGBSON(0);
    pgbson *value = PG_GETARG_PGBSON(1);
    pgbsonelement valueElement;
    PgbsonToSinglePgbsonElement(value, &valueElement);
    bson_value_t expressionValue = ConvertPgbsonToBsonValue(expression);
    ExprEvalState *evalState = GetExpressionEvalState(&expressionValue,
                                                     fcinfo->flinfo->fn_mcxt);
    pgbsonelement finalValue = { 0 };
    bool foundMatch = EvalExpressionAgainstArrayGetFirstMatch(evalState,
                                                             &valueElement,
                                                             &finalValue);
    if (!foundMatch)
    {
        PG_RETURN_NULL();
    }
    pgbson *result = PgbsonElementToPgbson(&finalValue);
    PG_RETURN_POINTER(result);
}
bool
EvalBooleanExpressionAgainstArray(ExprEvalState *evalState,
                                 const pgbsonelement *arrayElement)
{
    if (arrayElement->bsonValue.value_type != BSON_TYPE_ARRAY)
    {
        return false;
    }
    bson_iter_t arrayIterator;
    BsonValueInitIterator(&arrayElement->bsonValue, &arrayIterator);
    while (bson_iter_next(&arrayIterator))
    {
        pgbsonelement currentElement;
        PgbsonInitElementFromBsonIterator(&currentElement, &arrayIterator);
        Datum result = ExpressionEval(evalState, &currentElement);
        if (DatumGetBool(result))
        {
            return true;
        }
    }
    return false;
}
```

## 第54页 共60页

### 网关请求处理 - process.rs

```rust
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use deadpool_postgres::{HookError, PoolError};
use tokio_postgres::error::SqlState;
use crate::{
    configuration::DynamicConfiguration,
    context::ConnectionContext,
    error::{DocumentDBError, ErrorCode, Result},
    explain,
    postgres::PgDataClient,
    processor::{data_description, data_management},
    requests::{Request, RequestInfo, RequestType},
    responses::Response,
};
use super::{constant, cursor, indexing, ismaster, session, transaction, users};
enum Retry {
    Long,
    Short,
    None,
}
pub async fn process_request(
    request: &Request<'_>,
    request_info: &mut RequestInfo<'_>,
    connection_context: &mut ConnectionContext,
    pg_data_client: impl PgDataClient,
) -> Result<Response> {
    let dynamic_config = connection_context.dynamic_configuration();
    transaction::handle(request, request_info, connection_context, &pg_data_client).await?;
    let start_time = Instant::now();
    let mut retries = 0;
    let result = loop {
        let response = match request.request_type() {
            RequestType::Aggregate => {
                data_management::process_aggregate(
                    request,
                    request_info,
                    connection_context,
                    &pg_data_client,
                )
                .await
            }
            RequestType::BuildInfo => constant::process_build_info(&dynamic_config).await,
            RequestType::CollStats => {
                data_management::process_coll_stats(
                    request,
                    request_info,
                    connection_context,
                    &pg_data_client,
                )
                .await
            }
            RequestType::ConnectionStatus => constant::process_connection_status(),
            RequestType::Count => {
                data_management::process_count(
                    request,
                    request_info,
                    connection_context,
                    &pg_data_client,
                )
                .await
            }
            RequestType::Create => {
                data_description::process_create(
                    request,
                    request_info,
                    connection_context,
                    &pg_data_client,
                )
                .await
            }
            RequestType::CreateIndex | RequestType::CreateIndexes => {
                indexing::process_create_indexes(
                    request,
                    request_info,
                    connection_context,
                    &dynamic_config,
                    &pg_data_client,
                )
                .await
            }
            RequestType::Delete => {
                data_management::process_delete(
                    request,
                    request_info,
                    connection_context,
                    &dynamic_config,
                    &pg_data_client,
                )
                .await
            }
```

## 第55页 共60页

### PostgreSQL连接管理 - connection.rs

```rust
use std::time::Duration;
use super::{PgDocument, QueryCatalog};
use crate::{
    configuration::SetupConfiguration,
    error::Result,
    requests::{RequestInfo, RequestIntervalKind},
};
use deadpool_postgres::{Hook, HookError, Runtime};
use tokio::task::JoinHandle;
use tokio_postgres::{
    types::{ToSql, Type},
    NoTls, Row,
};
pub type InnerConnection = deadpool_postgres::Object;
pub fn pg_configuration(sc: &dyn SetupConfiguration) -> tokio_postgres::Config {
    let mut config = tokio_postgres::Config::new();
    config
        .host(sc.postgres_host_name())
        .port(sc.postgres_port())
        .dbname(sc.postgres_database());
    config
}
#[derive(Debug)]
pub struct ConnectionPool {
    pool: deadpool_postgres::Pool,
    _reaper: JoinHandle<()>,
}
impl ConnectionPool {
    pub fn new_with_user(
        sc: &dyn SetupConfiguration,
        query_catalog: &QueryCatalog,
        user: &str,
        pass: Option<&str>,
        application_name: String,
        max_size: usize,
    ) -> Result<Self> {
        let mut config = pg_configuration(sc);
        config.application_name(&application_name);
        config.user(user);
        if let Some(pass) = pass {
            config.password(pass);
        }
        let manager = deadpool_postgres::Manager::new(config, NoTls);
        let query_catalog_clone = query_catalog.clone();
        let builder = deadpool_postgres::Pool::builder(manager)
            .post_create(Hook::async_fn(move |m, _| {
                let timeout_ms = Duration::from_secs(120).as_millis().to_string();
                let query = query_catalog_clone.set_search_path_and_timeout(&timeout_ms);
                Box::pin(async move {
                    m.batch_execute(&query).await.map_err(HookError::Backend)?;
                    Ok(())
                })
            }))
            .create_timeout(Some(Duration::from_secs(5)))
            .wait_timeout(Some(Duration::from_secs(5)))
            .recycle_timeout(Some(Duration::from_secs(5)))
            .runtime(Runtime::Tokio1)
            .max_size(max_size);
        let pool = builder.build()?;
        let pool_copy = pool.clone();
        let reaper = tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(30));
            let max_age = Duration::from_secs(60);
            loop {
                interval.tick().await;
                pool_copy.retain(|_, metrics| metrics.last_used() < max_age);
            }
        });
        Ok(ConnectionPool {
            pool,
            _reaper: reaper,
        })
    }
    pub async fn get_inner_connection(&self) -> Result<InnerConnection> {
        Ok(self.pool.get().await?)
    }
}
```

## 第56页 共60页

### BSON聚合函数 - bson_aggregates.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <catalog/pg_type.h>
#include "io/bson_core.h"
#include "query/bson_compare.h"
#include <utils/array.h>
#include <utils/builtins.h>
#include <utils/heap_utils.h>
#include "utils/documentdb_errors.h"
#include "metadata/collection.h"
#include "commands/insert.h"
#include "sharding/sharding.h"
#include "utils/hashset_utils.h"
#include "aggregation/bson_aggregation_pipeline.h"
#include "aggregation/bson_tree.h"
#include "aggregation/bson_tree_write.h"
#include "aggregation/bson_sorted_accumulator.h"
#include "operators/bson_expression_operators.h"
typedef struct BsonNumericAggState
{
    bson_value_t sum;
    int64_t count;
} BsonNumericAggState;
typedef struct BsonArrayGroupAggState
{
    pgbson_writer writer;
    pgbson_array_writer arrayWriter;
} BsonArrayGroupAggState;
typedef struct BsonArrayWindowAggState
{
    List *aggregateList;
} BsonArrayWindowAggState;
typedef struct BsonArrayAggState
{
    union
    {
        BsonArrayGroupAggState group;
        BsonArrayWindowAggState window;
    } aggState;
    int64_t currentSizeWritten;
    bool isWindowAggregation;
} BsonArrayAggState;
typedef struct BsonObjectAggState
{
    BsonIntermediatePathNode *tree;
    int64_t currentSizeWritten;
    bool addEmptyPath;
} BsonObjectAggState;
typedef struct BsonAddToSetState
{
    HTAB *set;
    int64_t currentSizeWritten;
    bool isWindowAggregation;
} BsonAddToSetState;
typedef struct BsonOutAggregateState
{
    MongoCollection *stagingCollection;
    WriteError *writeError;
    bool isReplace;
    bool isUnique;
    bool isUpsert;
    bool isOrdered;
    bool isSharded;
    bool isTemporary;
    bool isDropTarget;
    bool isRenameTarget;
    bool isValidated;
    bool isIndexed;
    bool isPartitioned;
    bool isReplicated;
} BsonOutAggregateState;
PG_FUNCTION_INFO_V1(bson_out_transition);
PG_FUNCTION_INFO_V1(bson_out_final);
PG_FUNCTION_INFO_V1(bson_array_agg_transition);
PG_FUNCTION_INFO_V1(bson_array_agg_minvtransition);
PG_FUNCTION_INFO_V1(bson_distinct_array_agg_transition);
PG_FUNCTION_INFO_V1(bson_array_agg_final);
PG_FUNCTION_INFO_V1(bson_distinct_array_agg_final);
```

## 第57页 共60页

### 聚合状态转换函数 - bson_aggregates.c (续)

```c
Datum
bson_array_agg_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggContext = AggCheckCallContext(fcinfo, NULL);
    BsonArrayAggState *state = PG_ARGISNULL(0) ? NULL : (BsonArrayAggState *) PG_GETARG_POINTER(0);
    pgbson *value = PG_ARGISNULL(1) ? NULL : PG_GETARG_PGBSON(1);
    state = BsonArrayAggTransitionCore(state, value, aggContext, false);
    PG_RETURN_POINTER(state);
}
Datum
bson_sum_avg_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggContext = AggCheckCallContext(fcinfo, NULL);
    BsonNumericAggState *state = PG_ARGISNULL(0) ? NULL : (BsonNumericAggState *) PG_GETARG_POINTER(0);
    pgbson *value = PG_ARGISNULL(1) ? NULL : PG_GETARG_PGBSON(1);
    if (state == NULL)
    {
        MemoryContext oldContext = MemoryContextSwitchTo(aggContext);
        state = palloc0(sizeof(BsonNumericAggState));
        state->sum.value_type = BSON_TYPE_EOD;
        state->count = 0;
        MemoryContextSwitchTo(oldContext);
    }
    if (value != NULL)
    {
        pgbsonelement element;
        PgbsonToSinglePgbsonElement(value, &element);
        if (BsonValueIsNumber(&element.bsonValue))
        {
            MemoryContext oldContext = MemoryContextSwitchTo(aggContext);
            if (state->sum.value_type == BSON_TYPE_EOD)
            {
                state->sum = element.bsonValue;
                if (state->sum.value_type == BSON_TYPE_UTF8)
                {
                    state->sum.value.v_utf8.str = pstrdup(state->sum.value.v_utf8.str);
                }
                else if (state->sum.value_type == BSON_TYPE_DECIMAL128)
                {
                    state->sum.value.v_decimal128 = element.bsonValue.value.v_decimal128;
                }
            }
            else
            {
                state->sum = BsonValueAdd(&state->sum, &element.bsonValue);
            }
            state->count++;
            MemoryContextSwitchTo(oldContext);
        }
    }
    PG_RETURN_POINTER(state);
}
Datum
bson_sum_final(PG_FUNCTION_ARGS)
{
    BsonNumericAggState *state = PG_ARGISNULL(0) ? NULL : (BsonNumericAggState *) PG_GETARG_POINTER(0);
    if (state == NULL || state->count == 0)
    {
        PG_RETURN_NULL();
    }
    pgbson *result = BsonValueToPgbson(&state->sum);
    PG_RETURN_POINTER(result);
}
Datum
bson_avg_final(PG_FUNCTION_ARGS)
{
    BsonNumericAggState *state = PG_ARGISNULL(0) ? NULL : (BsonNumericAggState *) PG_GETARG_POINTER(0);
    if (state == NULL || state->count == 0)
    {
        PG_RETURN_NULL();
    }
    bson_value_t countValue;
    countValue.value_type = BSON_TYPE_INT64;
    countValue.value.v_int64 = state->count;
    bson_value_t avgValue = BsonValueDivide(&state->sum, &countValue);
    pgbson *result = BsonValueToPgbson(&avgValue);
    PG_RETURN_POINTER(result);
}
```

## 第58页 共60页

### BSON树结构操作 - bson_tree.c

```c
#include <postgres.h>
#include <lib/stringinfo.h>
#include <miscadmin.h>
#define BSON_TREE_PRIVATE
#include "aggregation/bson_tree.h"
#include "aggregation/bson_tree_private.h"
#undef BSON_TREE_PRIVATE
#include "io/bson_core.h"
#include "aggregation/bson_projection_tree.h"
static BsonLeafPathNode * GetOrAddLeafArrayChildNode(BsonLeafArrayWithFieldPathNode *tree,
                                                     const char *relativePath,
                                                     const StringView *fieldPath,
                                                     CreateLeafNodeFunc createFunc,
                                                     NodeType childNodeType);
static BsonLeafPathNode * CreateLeafNodeWithArrayField(const StringView *fieldPath,
                                                       const char *relativePath,
                                                       void *state);
static const BsonPathNode * ResetNodeWithValueOrField(const
                                                      BsonLeafPathNode *baseLeafNode,
                                                      const char *relativePath, const
                                                      bson_value_t *value,
                                                      CreateLeafNodeFunc createFunc,
                                                      bool forceLeafExpression,
                                                      bool treatLeafDataAsConstant,
                                                      void *nodeCreationState,
                                                      ParseAggregationExpressionContext *
                                                      parseContext);
static BsonPathNode * TraverseDottedPathAndGetOrAddNodeCore(const StringView *path,
                                                            const bson_value_t *value,
                                                            BsonIntermediatePathNode *tree,
                                                            CreateLeafNodeFunc createFunc,
                                                            CreateIntermediateNodeFunc
                                                            createIntermediateFunc,
                                                            bool forceLeafExpression,
                                                            bool treatNodeDataAsConstant,
                                                            void *nodeCreationState,
                                                            bool *nodeCreated,
                                                            ParseAggregationExpressionContext
                                                            *parseContext);
static void FreeBsonPathNode(BsonPathNode *node);
static void FreeLeafWithArrayFieldNodes(BsonLeafArrayWithFieldPathNode *leafArrayNode);
inline static StringView
Uint32ToStringView(uint32_t num)
{
    char *buffer = NULL;
    size_t bufferSize = 0;
    if (num >= 1000)
    {
        bufferSize = UINT32_MAX_STR_LEN * sizeof(char);
        buffer = (char *) palloc(bufferSize);
    }
    StringView s;
    s.length = bson_uint32_to_string(num, &(s.string), buffer,
                                     bufferSize);
    return s;
}
inline static bool
StringViewContainsDbRefsField(const StringView *source)
{
    return StringViewEqualsCString(source, "$id") ||
           StringViewEqualsCString(source, "$ref") ||
           StringViewEqualsCString(source, "$db");
}
```

## 第59页 共60页

### 响应写入器 - writer.rs

```rust
use crate::{
    context::ConnectionContext,
    error::DocumentDBError,
    protocol::{header::Header, opcode::OpCode},
};
use bson::{to_raw_document_buf, RawDocument};
use tokio::{
    io::{AsyncRead, AsyncWrite, AsyncWriteExt},
    net::TcpStream,
};
use tokio_openssl::SslStream;
use uuid::Uuid;
use super::{CommandError, Response};
pub async fn write<R>(
    header: &Header,
    response: &Response,
    stream: &mut R,
) -> Result<(), DocumentDBError>
where
    R: AsyncRead + AsyncWrite + Unpin + Send,
{
    write_response(header, response.as_raw_document()?, stream).await
}
pub async fn write_response<R>(
    header: &Header,
    response: &RawDocument,
    stream: &mut R,
) -> Result<(), DocumentDBError>
where
    R: AsyncRead + AsyncWrite + Unpin + Send,
{
    match header.op_code {
        OpCode::Command => unimplemented!(),
        OpCode::Msg => write_message(header, response, stream).await,
        OpCode::Query => {
            let header = Header {
                length: (response.as_bytes().len() + Header::LENGTH + 20) as i32,
                request_id: header.request_id,
                response_to: header.request_id,
                op_code: OpCode::Reply,
                activity_id: header.activity_id.clone(),
            };
            header.write_to(stream).await?;
            stream.write_i32_le(0).await?;
            stream.write_i64_le(0).await?;
            stream.write_i32_le(0).await?;
            stream.write_i32_le(1).await?;
            stream.write_all(response.as_bytes()).await?;
            Ok(())
        }
        OpCode::Insert => Ok(()),
        _ => Err(DocumentDBError::internal_error(format!(
            "Unexpected response opcode: {:?}",
            header.op_code
        ))),
    }?;
    stream.flush().await?;
    Ok(())
}
pub async fn write_message<R>(
    header: &Header,
    response: &RawDocument,
    writer: &mut R,
) -> Result<(), DocumentDBError>
where
    R: AsyncRead + AsyncWrite + Unpin + Send,
{
    let total_length = Header::LENGTH
        + std::mem::size_of::<u32>()
        + std::mem::size_of::<u8>()
        + response.as_bytes().len();
    let header = Header {
        length: total_length as i32,
        request_id: header.request_id,
        response_to: header.request_id,
        op_code: OpCode::Msg,
        activity_id: header.activity_id.clone(),
    };
    header.write_to(writer).await?;
    writer.write_u32_le(0).await?;
    writer.write_u8(0).await?;
    writer.write_all(response.as_bytes()).await?;
    Ok(())
}
```

## 第60页 共60页

### PostgreSQL函数管理工具 - fmgr_utils.c

```c
#include <postgres.h>
#include <fmgr.h>
#include <utils/builtins.h>
#include <utils/syscache.h>
#include <catalog/pg_proc.h>
#include <catalog/pg_type.h>
#include <access/htup_details.h>
#include "utils/documentdb_errors.h"
#include "io/bson_core.h"
static Oid GetFunctionOidByName(const char *functionName, int nargs, Oid *argtypes);
static bool IsFunctionExists(const char *functionName, int nargs, Oid *argtypes);
static Datum CallFunction(Oid functionOid, int nargs, Datum *args, bool *isNull);
Oid
GetFunctionOidByName(const char *functionName, int nargs, Oid *argtypes)
{
    List *funcname = list_make1(makeString((char *) functionName));
    Oid funcOid = LookupFuncName(funcname, nargs, argtypes, false);
    list_free_deep(funcname);
    return funcOid;
}
bool
IsFunctionExists(const char *functionName, int nargs, Oid *argtypes)
{
    List *funcname = list_make1(makeString((char *) functionName));
    Oid funcOid = LookupFuncName(funcname, nargs, argtypes, true);
    list_free_deep(funcname);
    return OidIsValid(funcOid);
}
Datum
CallFunction(Oid functionOid, int nargs, Datum *args, bool *isNull)
{
    FmgrInfo fmgrInfo;
    FunctionCallInfoBaseData fcinfo;
    fmgr_info(functionOid, &fmgrInfo);
    InitFunctionCallInfoData(fcinfo, &fmgrInfo, nargs, InvalidOid, NULL, NULL);
    for (int i = 0; i < nargs; i++)
    {
        fcinfo.args[i].value = args[i];
        fcinfo.args[i].isnull = false;
    }
    Datum result = FunctionCallInvoke(&fcinfo);
    if (isNull != NULL)
    {
        *isNull = fcinfo.isnull;
    }
    return result;
}
Datum
CallFunctionWithCollation(Oid functionOid, Oid collationOid, int nargs, Datum *args, bool *isNull)
{
    FmgrInfo fmgrInfo;
    FunctionCallInfoBaseData fcinfo;
    fmgr_info(functionOid, &fmgrInfo);
    InitFunctionCallInfoData(fcinfo, &fmgrInfo, nargs, collationOid, NULL, NULL);
    for (int i = 0; i < nargs; i++)
    {
        fcinfo.args[i].value = args[i];
        fcinfo.args[i].isnull = false;
    }
    Datum result = FunctionCallInvoke(&fcinfo);
    if (isNull != NULL)
    {
        *isNull = fcinfo.isnull;
    }
    return result;
}
```

---

**DocumentDB 源程序鉴别材料完成**

本文档共60页，展示了DocumentDB作为PostgreSQL基础文档数据库引擎的核心功能实现，包括：
- 网关架构：基于Rust的MongoDB协议处理器
- BSON集成：PostgreSQL内原生BSON数据类型
- 文档操作：文档集合的CRUD操作
- 查询处理：MongoDB查询到PostgreSQL的转换
- 认证实现：SCRAM-SHA-256安全认证机制
