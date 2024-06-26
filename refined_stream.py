import logging
from datetime import datetime
from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import Cluster
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col
from pyspark.sql.types import StructType, StructField, StringType

# Initialize logging
logging.basicConfig(level=logging.INFO)

def create_keyspace(session):
    session.execute("""
        CREATE KEYSPACE IF NOT EXISTS spark_streams
        WITH replication = {'class': 'SimpleStrategy', 'replication_factor': '1'};
    """)
    logging.info("Keyspace created successfully!")

def create_table(session):
    session.execute("""
        CREATE TABLE IF NOT EXISTS spark_streams.created_users (
            id UUID PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            gender TEXT,
            address TEXT,
            post_code TEXT,
            email TEXT,
            username TEXT,
            dob TEXT,
            registered_date TEXT,
            phone TEXT,
            picture TEXT
        );
    """)
    logging.info("Table created successfully!")

def insert_data(session, **kwargs):
    logging.info("Inserting data...")
    
    try:
        session.execute("""
            INSERT INTO spark_streams.created_users(
                id, first_name, last_name, gender, address, 
                post_code, email, username, dob, registered_date, phone, picture
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            kwargs.get('id'), kwargs.get('first_name'), kwargs.get('last_name'), kwargs.get('gender'), 
            kwargs.get('address'), kwargs.get('post_code'), kwargs.get('email'), kwargs.get('username'), 
            kwargs.get('dob'), kwargs.get('registered_date'), kwargs.get('phone'), kwargs.get('picture')
        ))
        logging.info(f"Data inserted for {kwargs.get('first_name')} {kwargs.get('last_name')}")
    except Exception as e:
        logging.error(f'Could not insert data due to: {e}')

def connect_to_kafka(spark_conn):
    try:
        spark_df = spark_conn.readStream \
            .format('kafka') \
            .option('kafka.bootstrap.servers', 'localhost:9092') \
            .option('subscribe', 'users_created') \
            .option('startingOffsets', 'earliest') \
            .load()
        logging.info("Kafka dataframe created successfully")
        return spark_df
    except Exception as e:
        logging.warning(f"Kafka dataframe could not be created because: {e}")
        return None

def create_spark_connection():
    try:
        s_conn = SparkSession.builder \
            .appName('SparkDataStream') \
            .config('spark.jars.packages', 
                    "com.datastax.spark:spark-cassandra-connector_2.13:3.4.1,"
                    "org.apache.spark:spark-sql-kafka-0-10_2.13:3.4.1") \
            .config('spark.cassandra.connection.host', 'localhost') \
            .getOrCreate()
        
        s_conn.sparkContext.setLogLevel("ERROR")
        logging.info("Spark connection created successfully")
        return s_conn
    except Exception as e:
        logging.error(f"Cannot create spark connection due to exception: {e}")
        return None

def create_cassandra_connection():
    try:
        cluster = Cluster(['localhost'])
        cas_session = cluster.connect()
        return cas_session
    except Exception as e:
        logging.error(f"Cannot create Cassandra connection due to: {e}")
        return None

def create_selection_df_from_kafka(spark_df):
    schema = StructType([
        StructField("id", StringType(), False),
        StructField("first_name", StringType(), False),
        StructField("last_name", StringType(), False),
        StructField("gender", StringType(), False),
        StructField("address", StringType(), False),
        StructField("post_code", StringType(), False),
        StructField("email", StringType(), False),
        StructField("username", StringType(), False),
        StructField("dob", StringType(), False),
        StructField("registered_date", StringType(), False),
        StructField("phone", StringType(), False),
        StructField("picture", StringType(), False)
    ])

    sel = spark_df.selectExpr("CAST(value AS STRING)") \
                  .select(from_json(col('value'), schema).alias('data')) \
                  .select("data.*")
    logging.info("Selection dataframe created from Kafka stream")
    return sel

if __name__ == "__main__":
    # Create Spark connection
    spark_conn = create_spark_connection()

    if spark_conn is not None:
        # Connect to Kafka with Spark connection
        spark_df = connect_to_kafka(spark_conn)
        
        if spark_df is not None:
            selection_df = create_selection_df_from_kafka(spark_df)
            session = create_cassandra_connection()

            if session is not None:
                create_keyspace(session)
                create_table(session)

                logging.info("Starting streaming...")

                streaming_query = selection_df.writeStream \
                    .format("org.apache.spark.sql.cassandra") \
                    .option('checkpointLocation', '/tmp/checkpoint') \
                    .option('keyspace', 'spark_streams') \
                    .option('table', 'created_users') \
                    .start()

                streaming_query.awaitTermination()
