import sys
sys.path.append("..")
import tensorflow as tf
import time
import numpy as np
from utils import conv_block, identity_block, inverted_residual_block


object_map = {
    0: "Airplane",
    1: "Automobile",
    2: "Bird",
    3: "Cat",
    4: "Deer",
    5: "dog",
    6: "Frog",
    7: "Horse",
    8: "Ship",
    9: "Truck"
}

class ModelWrapper():
    """
    Class that wraps tf.keras.Model to run a custom training loop
    """
    def __init__(self, model, optimizer=tf.keras.optimizers.Adam(), regularization=False):
        """
        inputs:
            model: expects tf.keras.Model object
            optimizers: expects tf.keras.optimizers object
        """
        self.model = model
        self.optimizer = optimizer
        self.regularization = regularization
        self.loss_objective = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True)
        self.train_loss = tf.keras.metrics.Mean(name="train_loss")
        self.valid_loss = tf.keras.metrics.Mean(name="valid_loss")
        self.train_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(name="train_accuracy")
        self.valid_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(name="valid_accuracy")
        self.best_weights = None
        self.best_model = None

    def fit(self, x_train, y_train, epochs, batch_size, validation_data):
        """
        Defines a custom training loop
        inputs:
            x_train: numpy array with the training dataset
            y_train: numpy array with the labels
            epochs: int number of epochs
            batch_size: int batch size
            validation_data: tuple in format (x_validation, y_validation)
        return:
            python dictionary with the metrics of the training,
            keys are loss, accuracy, val_loss, val_accuracy, each one is a list
            of the corresponding metric for each epoch
        """
        # work in progress
        train_ds = tf.data.Dataset.from_tensor_slices((x_train, y_train)).batch(batch_size)
        if not str(type(validation_data)).split(".")[-1].startswith("BatchDataset"):
            validation_data = tf.data.Dataset.from_tensor_slices((validation_data[0], validation_data[1])).batch(batch_size)
        epoch_train_loss = []
        epoch_train_accuracy = []
        epoch_valid_loss = []
        epoch_valid_accuracy = []
        best_acc = 0
        print("Starting training")
        for i in range(epochs):
            # Batch training
            self.train_loss.reset_states()
            self.valid_loss.reset_states()
            self.train_accuracy.reset_states()
            self.valid_accuracy.reset_states()
            training_begin = time.time()
            for images, labels in train_ds:
                self.train_step(images, labels)
            training_end = time.time()
            epoch_time = self.time_in_human_format(training_end - training_begin)
            # Validation
            for imgs, labels in validation_data:
                self.valid_step(imgs, labels)
            
            train_loss = self.train_loss.result()
            train_accuracy = self.train_accuracy.result()
            valid_loss = self.valid_loss.result()
            valid_accuracy = self.valid_accuracy.result()
            
            print(f"Epoch number {i}, training time: {epoch_time} -->  loss: {train_loss:.4f}, accuracy: {train_accuracy:.4f}, val_loss: {valid_loss:.4f}, val_accuracy: {valid_accuracy:.4f}")
            # Save metrics
            epoch_train_loss.append(train_loss)
            epoch_train_accuracy.append(train_accuracy)
            epoch_valid_loss.append(valid_loss)
            epoch_valid_accuracy.append(valid_accuracy)

            # Save the best performing model's weights
            if valid_accuracy > best_acc:
                best_acc = valid_accuracy
                self.best_weights = self.model.get_weights()
        
        self.best_model = tf.keras.models.clone_model(self.model)
        self.best_model.set_weights(self.best_weights)
        

        return {
            "loss": epoch_train_loss,
            "accuracy": epoch_train_accuracy,
            "val_loss": epoch_valid_loss,
            "val_accuracy": epoch_valid_accuracy
        }
    
    @tf.function
    def train_step(self, x_train, y_train):
        with tf.GradientTape() as tape:
            preds = self.model(x_train, training=True)
            loss = self.loss_objective(y_train, preds)
            if self.regularization:
                loss += tf.math.add_n(self.model.losses)

        grads = tape.gradient(loss, self.model.trainable_variables)
        self.optimizer.apply_gradients(zip(grads, self.model.trainable_variables))

        self.train_loss(loss)
        self.train_accuracy(y_train, preds)
    
    @tf.function
    def valid_step(self, x_test, y_valid):
        preds = self.model(x_test)
        valid_loss = self.loss_objective(y_valid, preds)

        self.valid_loss(valid_loss)
        self.valid_accuracy(y_valid, preds)

    def evaluate(self, test_ds, best=False):
        test_acc = tf.keras.metrics.SparseCategoricalAccuracy(name="test_accuracy")
        if best:
            if self.best_model:
                model = self.best_model
            else:
                model = self.model
        else:
            model = self.model

        for test_img, test_label in test_ds:
            preds = model(test_img, training=False)
            test_acc(test_label, preds)

        return f"Accuracy: {test_acc.result().numpy()}"
    
    def time_in_human_format(self, t):
        hours = int(t//3600)
        minutes = int((t - hours * 3600)//60)
        seconds = round(t - hours * 3600 - minutes * 60, 2)
        if hours > 0:
            return f"{hours} hours, {minutes} minutes, {seconds}s"
        elif minutes > 0:
            return f"{minutes} minutes, {seconds}s"
        else:
            return f"{seconds}s"

    def get_model(self):
        return self.model
    
    def get_best_model(self):
        return self.best_model
    

class EarlyStopLearningRateCallback(tf.keras.callbacks.Callback):
    def __init__(self, lr_patience=3, stop_patience=5):
        super(EarlyStopLearningRateCallback, self).__init__()
        self.lr_patience = lr_patience
        self.stop_patience = stop_patience
        self.best_weights = None
        self.best_acc = 0
        self.lr_wait = 0
        self.stop_wait = 0

    def on_train_begin(self, logs=None):
        self.start = time.time()

    def on_epoch_end(self, epoch, logs=None):
        """
        This function runs at the end of each epoch and
        checks if the accuracy of the network improves.
        if not and a number of epochs has passed, decrease learning rate by 50%
        if not and a number of epochs has passed, stop training
        """
        current_acc = logs.get("val_accuracy")
        if current_acc > self.best_acc:
            self.best_weights = self.model.get_weights()
            self.best_acc = current_acc
            self.lr_wait = 0
            self.stop_wait = 0
        else:
            self.lr_wait += 1
            self.stop_wait += 1
            if self.lr_wait == self.lr_patience:
                current_lr = tf.keras.backend.get_value(self.model.optimizer.learning_rate)
                new_lr = current_lr * 0.5
                tf.keras.backend.set_value(self.model.optimizer.learning_rate, new_lr)
                print("\nThe learning rate has changed, old value was {0} and the new value is {1}".format(current_lr, new_lr))
                self.lr_wait = 0
            if self.stop_wait == self.stop_patience:
                self.model.stop_training = True
                self.model.set_weights(self.best_weights)

    def on_train_end(self, logs):
        train_end = time.time() - self.start
        hours = int(train_end//3600)
        minutes = int((train_end - hours*3600)//60)
        seconds = round(train_end - hours*3600 - minutes*60, 0)
        print(f"Total training time -> {hours} hours, {minutes:2.0f} minutes, {seconds:2.2f} seconds")
        self.model.set_weights(self.best_weights)


def simple_dense_model(shape: tuple):
        """
        Defines a simple dense neural network
        inputs:
            shape: tuple, the shape of the input of the network
        returns:
            tf.keras.Model
        """
        inputs = tf.keras.Input(shape=shape)
        x = tf.keras.layers.Flatten(input_shape=shape)(inputs)
        x = tf.keras.layers.Dense(500, 
                                  activation="relu", 
                                  kernel_regularizer=tf.keras.regularizers.l2(),
                                  bias_regularizer=tf.keras.regularizers.l2())(x)
        x = tf.keras.layers.Dense(500, 
                                  activation="relu", 
                                  kernel_regularizer=tf.keras.regularizers.l2(),
                                  bias_regularizer=tf.keras.regularizers.l2())(x)
        x = tf.keras.layers.Dense(500, 
                                  activation="relu", 
                                  kernel_regularizer=tf.keras.regularizers.l2(),
                                  bias_regularizer=tf.keras.regularizers.l2())(x)
        x = tf.keras.layers.Dense(500, 
                                  activation="relu", 
                                  kernel_regularizer=tf.keras.regularizers.l2(),
                                  bias_regularizer=tf.keras.regularizers.l2())(x)
        x = tf.keras.layers.Dense(500, 
                                  activation="relu", 
                                  kernel_regularizer=tf.keras.regularizers.l2(),
                                  bias_regularizer=tf.keras.regularizers.l2())(x)
        outputs = tf.keras.layers.Dense(10)(x)

        return tf.keras.Model(inputs, outputs)  

def simple_conv_model(shape: tuple):
    """
    Defines a simple convolutional neural network
    inputs:
        shape: tuple, the shape of the input of the network
    returns:
        tf.keras.Model
    """  
    inputs = tf.keras.Input(shape=shape)
    x = tf.keras.layers.Conv2D(filters=32, kernel_size=(5,5), activation="relu")(inputs)
    x = tf.keras.layers.Conv2D(filters=64, kernel_size=(3,3), activation="relu")(x)
    x = tf.keras.layers.Conv2D(filters=128, kernel_size=(3,3), activation="relu")(x)
    x = tf.keras.layers.Conv2D(filters=256, kernel_size=(3,3), activation="relu")(x)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dense(100, activation="relu")(x)
    outputs = tf.keras.layers.Dense(10)(x)

    return tf.keras.Model(inputs, outputs)

def conv_model(shape: tuple):
    """
    Defines a convolutional neural network with optimizations
    """
    if tf.keras.backend.image_data_format() == "channels_last":
        bn_axis = 3
    else:
        bn_axis = 1

    inputs = tf.keras.Input(shape=shape)
    x = tf.keras.layers.Conv2D(filters=32, 
                               kernel_size=(5,5))(inputs)
    x = tf.keras.layers.BatchNormalization(axis=bn_axis)(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = tf.keras.layers.MaxPool2D()(x)
    x = tf.keras.layers.Conv2D(filters=64, 
                               kernel_size=(3,3), 
                               padding="same")(x)
    x = tf.keras.layers.BatchNormalization(axis=bn_axis)(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = tf.keras.layers.MaxPool2D()(x)
    x = tf.keras.layers.Conv2D(filters=128, 
                               kernel_size=(3,3), 
                               padding="same")(x)
    x = tf.keras.layers.Dropout(0.45)(x)
    x = tf.keras.layers.BatchNormalization(axis=bn_axis)(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = tf.keras.layers.MaxPool2D()(x)
    x = tf.keras.layers.Conv2D(filters=256, 
                               kernel_size=(3,3),
                               kernel_regularizer=tf.keras.regularizers.l2(0.012))(x)
    x = tf.keras.layers.Dropout(0.45)(x)
    x = tf.keras.layers.BatchNormalization(axis=bn_axis)(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.Dropout(0.45)(x)
    x = tf.keras.layers.Dense(100, activation="relu",
                              kernel_regularizer=tf.keras.regularizers.l2(0.012))(x)
    x = tf.keras.layers.Dropout(0.45)(x)
    outputs = tf.keras.layers.Dense(10)(x)

    return tf.keras.Model(inputs, outputs)

def residual_model(shape):
    """
    Defines a residual convolutional neural network with optimizations
    """
    if tf.keras.backend.image_data_format() == "channels_last":
        bn_axis = 3
    else:
        bn_axis = 1

    inputs = tf.keras.Input(shape=shape)
    x = tf.keras.layers.Conv2D(64, (5,5), padding="same")(inputs)
    x = tf.keras.layers.BatchNormalization(axis=bn_axis)(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = identity_block(x, [128,128], bn_axis=bn_axis)
    x = conv_block(x, [64, 128, 128], bn_axis=bn_axis)
    x = conv_block(x , [128, 256,256], bn_axis=bn_axis)
    x = identity_block(x, [256,256], bn_axis=bn_axis)
    x = conv_block(x, [128, 512, 512], bn_axis=bn_axis)
    x = conv_block(x, [256, 512, 512], bn_axis=bn_axis)
    x = identity_block(x, [512,512], bn_axis=bn_axis)
    x = conv_block(x, [256, 1024, 1024], bn_axis=bn_axis)
    x = conv_block(x, [512, 1024, 1024], bn_axis=bn_axis)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dense(100, activation="relu")(x)
    x = tf.keras.layers.Dropout(0.25)(x)
    outputs = tf.keras.layers.Dense(10)(x)

    return tf.keras.Model(inputs, outputs)

def bottleneck_model(shape):
    """
    Defines a model using transfer learning
    """

    if tf.keras.backend.image_data_format() == "channels_last":
        bn_axis = 3
    else:
        bn_axis = 1

    inputs = tf.keras.Input(shape=shape)
    x = tf.keras.layers.Conv2D(64, kernel_size=(5,5), padding="same")(inputs)
    x = tf.keras.layers.BatchNormalization(axis=bn_axis)(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = inverted_residual_block(x, 2, 1, 64)
    x = tf.keras.layers.Conv2D(128, kernel_size=(3,3), padding="same")(x)
    x = tf.keras.layers.BatchNormalization(axis=bn_axis)(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = inverted_residual_block(x, 2, 1, 128)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dense(100, activation="relu")(x)
    outputs = tf.keras.layers.Dense(10)(x)

    return tf.keras.Model(inputs, outputs)