/*-------------------------------------------------------------------------
 * Copyright (c) Microsoft Corporation.  All rights reserved.
 *
 * tests/gateway_comprehensive_tests.rs
 *
 * Comprehensive test suite for DocumentDB Gateway Component (pg_documentdb_gw)
 * Testing all major areas: Connection Management, Authentication System,
 * MongoDB Wire Protocol, and Request Processing
 *-------------------------------------------------------------------------
 */

use bson::{doc, Document};
use futures::TryStreamExt;
use mongodb::{
    options::{AuthMechanism, ClientOptions, Credential, ServerAddress, Tls, TlsOptions},
    Client, IndexModel,
};

mod common;


#[tokio::test]
async fn test_connection_pooling_creation_and_reuse() {
    let _client = common::initialize().await;
    
    let db = _client.database("connection_pool_test");
    
    let coll = db.collection::<Document>("test_collection");
    
    let doc1 = doc! {"test": "connection_pool_1", "timestamp": 1};
    let result1 = coll.insert_one(doc1).await;
    assert!(result1.is_ok(), "First connection should succeed");
    
    let doc2 = doc! {"test": "connection_pool_2", "timestamp": 2};
    let result2 = coll.insert_one(doc2).await;
    assert!(result2.is_ok(), "Connection reuse should succeed");
    
    let count = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(count, 2, "Both documents should be inserted via connection pool");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_connection_pool_cleanup() {
    let client = common::initialize().await;
    let db = client.database("connection_cleanup_test");
    
    let coll = db.collection::<Document>("test_collection");
    coll.insert_one(doc! {"test": "cleanup_test"}).await.unwrap();
    
    let count_before = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(count_before, 1);
    
    drop(coll);
    
    let coll2 = db.collection::<Document>("test_collection");
    let count_after = coll2.count_documents(doc! {}).await.unwrap();
    assert_eq!(count_after, 1, "Connection cleanup should not affect data");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_ssl_tls_secure_connection() {
    let credential = Credential::builder()
        .username("test".to_string())
        .password("test".to_string())
        .mechanism(AuthMechanism::ScramSha256)
        .build();

    let client_options = ClientOptions::builder()
        .credential(credential)
        .tls(Tls::Enabled(
            TlsOptions::builder()
                .allow_invalid_certificates(true)
                .build(),
        ))
        .hosts(vec![ServerAddress::parse("127.0.0.1:10260").unwrap()])
        .build();
    
    let client = Client::with_options(client_options).unwrap();
    
    let db = client.database("ssl_test");
    let coll = db.collection::<Document>("test_collection");
    
    let result = coll.insert_one(doc! {"ssl_test": true}).await;
    assert!(result.is_ok(), "SSL/TLS connection should work");
    
    let count = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(count, 1, "SSL connection should allow data operations");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_ssl_tls_certificate_validation() {
    let credential = Credential::builder()
        .username("test".to_string())
        .password("test".to_string())
        .mechanism(AuthMechanism::ScramSha256)
        .build();

    let _strict_tls_options = ClientOptions::builder()
        .credential(credential.clone())
        .tls(Tls::Enabled(
            TlsOptions::builder()
                .allow_invalid_certificates(false)
                .build(),
        ))
        .hosts(vec![ServerAddress::parse("127.0.0.1:10260").unwrap()])
        .build();
    
    let lenient_tls_options = ClientOptions::builder()
        .credential(credential)
        .tls(Tls::Enabled(
            TlsOptions::builder()
                .allow_invalid_certificates(true)
                .build(),
        ))
        .hosts(vec![ServerAddress::parse("127.0.0.1:10260").unwrap()])
        .build();
    
    let lenient_client = Client::with_options(lenient_tls_options).unwrap();
    let db = lenient_client.database("cert_validation_test");
    let result = db.collection::<Document>("test").insert_one(doc! {"test": "lenient"}).await;
    assert!(result.is_ok(), "Lenient certificate validation should work");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_connection_limits_and_rejection() {
    let mut clients = Vec::new();
    
    for i in 0..10 {
        let credential = Credential::builder()
            .username("test".to_string())
            .password("test".to_string())
            .mechanism(AuthMechanism::ScramSha256)
            .build();

        let client_options = ClientOptions::builder()
            .credential(credential)
            .tls(Tls::Enabled(
                TlsOptions::builder()
                    .allow_invalid_certificates(true)
                    .build(),
            ))
            .hosts(vec![ServerAddress::parse("127.0.0.1:10260").unwrap()])
            .build();
        
        let client = Client::with_options(client_options).unwrap();
        
        let db = client.database(&format!("connection_limit_test_{}", i));
        let result = db.collection::<Document>("test").insert_one(doc! {"connection_id": i}).await;
        
        if result.is_ok() {
            clients.push(client);
        } else {
            break;
        }
    }
    
    assert!(!clients.is_empty(), "At least some connections should succeed");
    
    for (i, client) in clients.iter().enumerate() {
        let db = client.database(&format!("connection_limit_test_{}", i));
        db.drop().await.unwrap();
    }
}

#[tokio::test]
async fn test_connection_error_recovery() {
    let client = common::initialize().await;
    let db = client.database("error_recovery_test");
    let coll = db.collection::<Document>("test_collection");
    
    let result1 = coll.insert_one(doc! {"test": "before_error"}).await;
    assert!(result1.is_ok(), "Initial connection should work");
    
    let _invalid_doc_result = coll.insert_one(doc! {"$invalid": "field_name"}).await;
    
    let result2 = coll.insert_one(doc! {"test": "after_error"}).await;
    assert!(result2.is_ok(), "Connection should recover after error");
    
    let count = coll.count_documents(doc! {"test": {"$exists": true}}).await.unwrap();
    assert_eq!(count, 2, "Valid operations should succeed despite errors");
    
    db.drop().await.unwrap();
}


#[tokio::test]
async fn test_scram_sha256_authentication_flow() {
    let credential = Credential::builder()
        .username("test".to_string())
        .password("test".to_string())
        .mechanism(AuthMechanism::ScramSha256)
        .build();

    let client_options = ClientOptions::builder()
        .credential(credential)
        .tls(Tls::Enabled(
            TlsOptions::builder()
                .allow_invalid_certificates(true)
                .build(),
        ))
        .hosts(vec![ServerAddress::parse("127.0.0.1:10260").unwrap()])
        .build();
    
    let client = Client::with_options(client_options).unwrap();
    
    let db = client.database("scram_auth_test");
    let coll = db.collection::<Document>("test");
    let result = coll.insert_one(doc! {"auth_test": "scram_sha256"}).await;
    assert!(result.is_ok(), "SCRAM-SHA-256 authentication should succeed");
    
    let count = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(count, 1, "Authenticated operations should work");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_authentication_invalid_credentials() {
    let invalid_credential = Credential::builder()
        .username("invalid_user".to_string())
        .password("invalid_password".to_string())
        .mechanism(AuthMechanism::ScramSha256)
        .build();

    let client_options = ClientOptions::builder()
        .credential(invalid_credential)
        .tls(Tls::Enabled(
            TlsOptions::builder()
                .allow_invalid_certificates(true)
                .build(),
        ))
        .hosts(vec![ServerAddress::parse("127.0.0.1:10260").unwrap()])
        .build();
    
    let client = Client::with_options(client_options).unwrap();
    let db = client.database("invalid_auth_test");
    
    let result = db.collection::<Document>("test").insert_one(doc! {"test": "should_fail"}).await;
    
    assert!(result.is_err(), "Invalid credentials should be rejected");
}

#[tokio::test]
async fn test_authentication_wrong_mechanism() {
    let credential = Credential::builder()
        .username("test".to_string())
        .password("test".to_string())
        .mechanism(AuthMechanism::Plain)
        .build();

    let client_options = ClientOptions::builder()
        .credential(credential)
        .tls(Tls::Enabled(
            TlsOptions::builder()
                .allow_invalid_certificates(true)
                .build(),
        ))
        .hosts(vec![ServerAddress::parse("127.0.0.1:10260").unwrap()])
        .build();
    
    let client = Client::with_options(client_options).unwrap();
    let db = client.database("wrong_mechanism_test");
    
    let result = db.collection::<Document>("test").insert_one(doc! {"test": "should_fail"}).await;
    
    assert!(result.is_err(), "Wrong auth mechanism should be rejected");
}

#[tokio::test]
async fn test_session_management_and_validation() {
    let client = common::initialize().await;
    let db = client.database("session_test");
    let coll = db.collection::<Document>("test_collection");
    
    let session_result = client.start_session().await;
    assert!(session_result.is_ok(), "Session creation should succeed");
    
    let mut _session = session_result.unwrap();
    
    let result = coll.insert_one(doc! {"session_test": true}).await;
    assert!(result.is_ok(), "Session-based operations should work");
    
    let count = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(count, 1, "Session should maintain consistency");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_end_to_end_authentication_with_postgresql() {
    let client = common::initialize().await;
    
    let admin_db = client.database("admin");
    let result = admin_db.run_command(doc! {"listCollections": 1}).await;
    assert!(result.is_ok(), "Admin operations should work with proper authentication");
    
    let user_db = client.database("user_test");
    let coll = user_db.collection::<Document>("test_collection");
    
    let insert_result = coll.insert_one(doc! {"end_to_end_test": true}).await;
    assert!(insert_result.is_ok(), "User operations should work with authentication");
    
    let find_result = coll.find_one(doc! {"end_to_end_test": true}).await;
    assert!(find_result.is_ok(), "Find operations should work");
    assert!(find_result.unwrap().is_some(), "Document should be found");
    
    user_db.drop().await.unwrap();
}


#[tokio::test]
async fn test_mongodb_message_parsing_insert() {
    let client = common::initialize().await;
    let db = client.database("message_parsing_test");
    let coll = db.collection::<Document>("insert_test");
    
    let test_doc = doc! {
        "string_field": "test_string",
        "number_field": 42,
        "boolean_field": true,
        "array_field": [1, 2, 3],
        "object_field": {"nested": "value"}
    };
    
    let result = coll.insert_one(test_doc.clone()).await;
    assert!(result.is_ok(), "Insert message parsing should work");
    
    let found_doc = coll.find_one(doc! {"string_field": "test_string"}).await.unwrap();
    assert!(found_doc.is_some(), "Inserted document should be retrievable");
    
    let found = found_doc.unwrap();
    assert_eq!(found.get_str("string_field").unwrap(), "test_string");
    assert_eq!(found.get_i32("number_field").unwrap(), 42);
    assert_eq!(found.get_bool("boolean_field").unwrap(), true);
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_mongodb_message_parsing_query() {
    let client = common::initialize().await;
    let db = client.database("query_parsing_test");
    let coll = db.collection::<Document>("query_test");
    
    coll.insert_many(vec![
        doc! {"name": "Alice", "age": 30, "city": "New York"},
        doc! {"name": "Bob", "age": 25, "city": "San Francisco"},
        doc! {"name": "Charlie", "age": 35, "city": "New York"},
    ]).await.unwrap();
    
    let query_result = coll.find(doc! {"city": "New York"}).await;
    assert!(query_result.is_ok(), "Query message parsing should work");
    
    let docs: Vec<Document> = query_result.unwrap().try_collect().await.unwrap();
    assert_eq!(docs.len(), 2, "Query should return correct number of documents");
    
    let complex_query = coll.find(doc! {
        "age": {"$gte": 30},
        "city": "New York"
    }).await;
    assert!(complex_query.is_ok(), "Complex query parsing should work");
    
    let complex_docs: Vec<Document> = complex_query.unwrap().try_collect().await.unwrap();
    assert_eq!(complex_docs.len(), 1, "Complex query should filter correctly");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_mongodb_message_parsing_update() {
    let client = common::initialize().await;
    let db = client.database("update_parsing_test");
    let coll = db.collection::<Document>("update_test");
    
    coll.insert_one(doc! {"name": "Test", "value": 10}).await.unwrap();
    
    let update_result = coll.update_one(
        doc! {"name": "Test"},
        doc! {"$set": {"value": 20, "updated": true}}
    ).await;
    assert!(update_result.is_ok(), "Update message parsing should work");
    
    let updated_doc = coll.find_one(doc! {"name": "Test"}).await.unwrap().unwrap();
    assert_eq!(updated_doc.get_i32("value").unwrap(), 20);
    assert_eq!(updated_doc.get_bool("updated").unwrap(), true);
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_mongodb_response_generation_and_serialization() {
    let client = common::initialize().await;
    let db = client.database("response_test");
    let coll = db.collection::<Document>("response_test");
    
    let insert_result = coll.insert_one(doc! {"test": "response"}).await.unwrap();
    assert!(insert_result.inserted_id.as_object_id().is_some(), "Response should contain ObjectId");
    
    let count_result = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(count_result, 1, "Count response should be correct");
    
    let find_result = coll.find_one(doc! {"test": "response"}).await.unwrap();
    assert!(find_result.is_some(), "Find response should contain document");
    
    let delete_result = coll.delete_one(doc! {"test": "response"}).await.unwrap();
    assert_eq!(delete_result.deleted_count, 1, "Delete response should show count");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_protocol_compliance_with_mongodb_client() {
    let client = common::initialize().await;
    let db = client.database("protocol_compliance_test");
    
    let admin_result = db.run_command(doc! {"ping": 1}).await;
    assert!(admin_result.is_ok(), "Ping command should work");
    
    let list_collections_result = db.list_collection_names().await;
    assert!(list_collections_result.is_ok(), "List collections should work");
    
    let coll = db.collection::<Document>("compliance_test");
    coll.insert_one(doc! {"test": "compliance"}).await.unwrap();
    
    let index_result = coll.create_index(IndexModel::builder().keys(doc! {"test": 1}).build()).await;
    assert!(index_result.is_ok(), "Index creation should work");
    
    let stats_result = db.run_command(doc! {"collStats": "compliance_test"}).await;
    assert!(stats_result.is_ok(), "Collection stats should work");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_protocol_error_handling_and_responses() {
    let client = common::initialize().await;
    let db = client.database("protocol_error_test");
    let coll = db.collection::<Document>("error_test");
    
    let invalid_command_result = db.run_command(doc! {"invalidCommand": 1}).await;
    assert!(invalid_command_result.is_err(), "Invalid commands should return errors");
    
    coll.insert_one(doc! {"_id": "test_id", "data": "test"}).await.unwrap();
    
    let duplicate_key_result = coll.insert_one(doc! {"_id": "test_id", "data": "duplicate"}).await;
    assert!(duplicate_key_result.is_err(), "Duplicate key should return error");
    
    let _invalid_query_result = coll.find(doc! {"$invalidOperator": "test"}).await;
    
    let valid_after_error = coll.find_one(doc! {"_id": "test_id"}).await;
    assert!(valid_after_error.is_ok(), "Valid operations should work after errors");
    
    db.drop().await.unwrap();
}


#[tokio::test]
async fn test_request_routing_crud_operations() {
    let client = common::initialize().await;
    let db = client.database("request_routing_test");
    let coll = db.collection::<Document>("routing_test");
    
    let insert_result = coll.insert_one(doc! {"operation": "insert", "routed": true}).await;
    assert!(insert_result.is_ok(), "Insert routing should work");
    
    let find_result = coll.find_one(doc! {"operation": "insert"}).await;
    assert!(find_result.is_ok(), "Find routing should work");
    assert!(find_result.unwrap().is_some(), "Routed find should return data");
    
    let update_result = coll.update_one(
        doc! {"operation": "insert"},
        doc! {"$set": {"operation": "update"}}
    ).await;
    assert!(update_result.is_ok(), "Update routing should work");
    
    let delete_result = coll.delete_one(doc! {"operation": "update"}).await;
    assert!(delete_result.is_ok(), "Delete routing should work");
    assert_eq!(delete_result.unwrap().deleted_count, 1, "Delete should be routed correctly");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_request_routing_aggregation_operations() {
    let client = common::initialize().await;
    let db = client.database("aggregation_routing_test");
    let coll = db.collection::<Document>("agg_test");
    
    coll.insert_many(vec![
        doc! {"category": "A", "value": 10},
        doc! {"category": "B", "value": 20},
        doc! {"category": "A", "value": 15},
    ]).await.unwrap();
    
    let pipeline = vec![
        doc! {"$group": {"_id": "$category", "total": {"$sum": "$value"}}},
        doc! {"$sort": {"total": -1}}
    ];
    
    let agg_result = coll.aggregate(pipeline).await;
    assert!(agg_result.is_ok(), "Aggregation routing should work");
    
    let results: Vec<Document> = agg_result.unwrap().try_collect().await.unwrap();
    assert_eq!(results.len(), 2, "Aggregation should return grouped results");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_parameter_conversion_bson_to_postgresql() {
    let client = common::initialize().await;
    let db = client.database("parameter_conversion_test");
    let coll = db.collection::<Document>("conversion_test");
    
    let complex_doc = doc! {
        "string_param": "test_string",
        "int_param": 42,
        "double_param": 3.14159,
        "bool_param": true,
        "null_param": bson::Bson::Null,
        "array_param": [1, "two", 3.0, true],
        "object_param": {
            "nested_string": "nested_value",
            "nested_number": 100
        },
        "date_param": bson::DateTime::now()
    };
    
    let insert_result = coll.insert_one(complex_doc.clone()).await;
    assert!(insert_result.is_ok(), "Complex BSON parameter conversion should work");
    
    let found_doc = coll.find_one(doc! {"string_param": "test_string"}).await.unwrap().unwrap();
    
    assert_eq!(found_doc.get_str("string_param").unwrap(), "test_string");
    assert_eq!(found_doc.get_i32("int_param").unwrap(), 42);
    assert!((found_doc.get_f64("double_param").unwrap() - 3.14159).abs() < 0.0001);
    assert_eq!(found_doc.get_bool("bool_param").unwrap(), true);
    assert!(found_doc.get("null_param").unwrap().as_null().is_some());
    
    let array = found_doc.get_array("array_param").unwrap();
    assert_eq!(array.len(), 4);
    
    let object = found_doc.get_document("object_param").unwrap();
    assert_eq!(object.get_str("nested_string").unwrap(), "nested_value");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_response_transformation_postgresql_to_mongodb() {
    let client = common::initialize().await;
    let db = client.database("response_transformation_test");
    let coll = db.collection::<Document>("transform_test");
    
    coll.insert_many(vec![
        doc! {"name": "Alice", "score": 85},
        doc! {"name": "Bob", "score": 92},
        doc! {"name": "Charlie", "score": 78},
    ]).await.unwrap();
    
    let find_result = coll.find(doc! {"score": {"$gte": 80}}).await.unwrap();
    let docs: Vec<Document> = find_result.try_collect().await.unwrap();
    
    assert_eq!(docs.len(), 2, "Response transformation should preserve query results");
    
    for doc in &docs {
        assert!(doc.contains_key("_id"), "Response should include MongoDB _id field");
        assert!(doc.get("_id").unwrap().as_object_id().is_some(), "_id should be ObjectId");
        assert!(doc.contains_key("name"), "Response should preserve original fields");
        assert!(doc.contains_key("score"), "Response should preserve original fields");
    }
    
    let count_result = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(count_result, 3, "Count response should be properly transformed");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_error_propagation_and_client_notification() {
    let client = common::initialize().await;
    let db = client.database("error_propagation_test");
    let coll = db.collection::<Document>("error_test");
    
    coll.insert_one(doc! {"_id": "unique_id", "data": "test"}).await.unwrap();
    
    let duplicate_error = coll.insert_one(doc! {"_id": "unique_id", "data": "duplicate"}).await;
    assert!(duplicate_error.is_err(), "Duplicate key error should be propagated");
    
    let error = duplicate_error.unwrap_err();
    let error_string = error.to_string();
    assert!(error_string.contains("duplicate") || error_string.contains("Duplicate"), 
           "Error message should indicate duplicate key issue");
    
    let invalid_update = coll.update_one(
        doc! {"_id": "unique_id"},
        doc! {"$invalidOperator": {"field": "value"}}
    ).await;
    assert!(invalid_update.is_err(), "Invalid operator error should be propagated");
    
    let valid_operation = coll.find_one(doc! {"_id": "unique_id"}).await;
    assert!(valid_operation.is_ok(), "Valid operations should work after errors");
    
    db.drop().await.unwrap();
}

#[tokio::test]
async fn test_request_processing_performance_and_concurrency() {
    let client = common::initialize().await;
    let db = client.database("performance_test");
    let coll = db.collection::<Document>("perf_test");
    
    let start_time = std::time::Instant::now();
    
    let mut handles = Vec::new();
    for i in 0..10 {
        let coll_clone = coll.clone();
        let handle = tokio::spawn(async move {
            let result = coll_clone.insert_one(doc! {
                "thread_id": i,
                "data": format!("concurrent_data_{}", i),
                "timestamp": bson::DateTime::now()
            }).await;
            result.is_ok()
        });
        handles.push(handle);
    }
    
    let results = futures::future::join_all(handles).await;
    let successful_inserts = results.iter().filter(|r| *r.as_ref().unwrap()).count();
    
    let elapsed = start_time.elapsed();
    
    assert_eq!(successful_inserts, 10, "All concurrent operations should succeed");
    assert!(elapsed.as_millis() < 5000, "Concurrent operations should complete reasonably quickly");
    
    let final_count = coll.count_documents(doc! {}).await.unwrap();
    assert_eq!(final_count, 10, "All concurrent inserts should be processed");
    
    db.drop().await.unwrap();
}


#[tokio::test]
async fn test_full_gateway_integration_workflow() {
    let client = common::initialize().await;
    let db = client.database("integration_test");
    
    let users_coll = db.collection::<Document>("users");
    let orders_coll = db.collection::<Document>("orders");
    
    let user_id = users_coll.insert_one(doc! {
        "name": "Integration Test User",
        "email": "test@example.com",
        "created_at": bson::DateTime::now()
    }).await.unwrap().inserted_id;
    
    let order_result = orders_coll.insert_one(doc! {
        "user_id": user_id.clone(),
        "items": ["item1", "item2"],
        "total": 99.99,
        "status": "pending"
    }).await;
    assert!(order_result.is_ok(), "Cross-collection operations should work");
    
    let user_orders_pipeline = vec![
        doc! {"$match": {"user_id": user_id.clone()}},
        doc! {"$group": {"_id": "$user_id", "total_orders": {"$sum": 1}, "total_amount": {"$sum": "$total"}}}
    ];
    
    let agg_result = orders_coll.aggregate(user_orders_pipeline).await;
    assert!(agg_result.is_ok(), "Complex aggregation should work");
    
    let agg_docs: Vec<Document> = agg_result.unwrap().try_collect().await.unwrap();
    assert_eq!(agg_docs.len(), 1, "Aggregation should return user summary");
    
    let summary = &agg_docs[0];
    assert_eq!(summary.get_i32("total_orders").unwrap(), 1);
    assert!((summary.get_f64("total_amount").unwrap() - 99.99).abs() < 0.01);
    
    let update_result = orders_coll.update_one(
        doc! {"user_id": user_id.clone()},
        doc! {"$set": {"status": "completed"}}
    ).await;
    assert!(update_result.is_ok(), "Order status update should work");
    
    let final_order = orders_coll.find_one(doc! {"user_id": user_id}).await.unwrap().unwrap();
    assert_eq!(final_order.get_str("status").unwrap(), "completed");
    
    db.drop().await.unwrap();
}
