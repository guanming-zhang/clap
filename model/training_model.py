import pytorch_lightning as pl
from torch import optim
import loss_module
import torch
import models
import torch.nn.functional as F

class CLAP(pl.LightningModule):
    def __init__(self,embedded_dim:int,backbone_name:str,use_projection_header:bool,proj_dim:int,
                 optim_name:str,lr:float,momentum:float,weight_decay:float, 
                 warmup_epochs:int,n_epochs:int,
                 n_views:int,batch_size:int,lw0:float,lw1:float,lw2:float,n_pow_iter:int=20,rs:float=2.0,margin:float=1e-7):
        super().__init__()
        # all the hyperparameters are added as attributes to this class
        self.save_hyperparameters()
        self.backbone = models.BackboneNet(embedded_dim,backbone_name,use_projection_header,proj_dim)
        self.loss_fn = loss_module.EllipsoidPackingLoss(n_views,batch_size,lw0,lw1,lw2,n_pow_iter,rs,margin)
        self.train_epoch_loss = []  # To store epoch loss for training

    def configure_optimizers(self):
        if self.optim_name == "SGD":
            optimizer = optim.SGD(params=self.backbone.parameters() ,lr=self.lr,momentum=self.momentum)
        elif self.optim_name == "AdamW":
            optimizer = optim.AdamW(params=self.backbone.parameters() ,lr=self.lr,momentum=self.momentume)
        else:
            raise NotImplementedError("optimizer:"+ self.optimizer +" not implemented")
        linear = optim.lr_scheduler.LinearLR(optimizer,total_iters=self.warmup_epochs)
        cosine = optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=self.n_epochs - self.warmup_epochs)
        scheduler = optim.lr_scheduler.SequentialLR(schedulers=[linear, cosine], milestones=[self.warmup_epochs])
        return [optimizer],[scheduler]
    
    def training_step(self, batch, batch_idx):
        imgs,labels = batch
        imgs = torch.cat(imgs,dim=0)
        preds = self.backbone(imgs)
        # the labels are dummy since label is not used in ssl
        return self.loss_fn(preds,None)
    
    def training_epoch_end(self, outputs):
        # `outputs` is a list of losses from each batch returned by training_step()
        avg_loss = torch.stack([x['loss'] for x in outputs]).mean()  # Compute the average loss for the epoch
        self.log('train_epoch_loss', avg_loss, prog_bar=True)  # Log epoch loss

        # Save epoch loss for future reference
        self.train_epoch_loss.append(avg_loss.item())

class LinearClassification(pl.LightningModule):
    def __init__(self,backbone:torch.nn.modules,
                 in_dim:int,out_dim:int,use_batch_norm:bool,
                 n_epochs:int):
        super().__init__()
        self.save_hyperparameters(ignore=["backbone"])
        self.backbone = backbone
        if use_batch_norm:
            self.linear_net = models.BnLinearNet(in_dim,out_dim)
        else:
            self.linear_net = torch.nn.Linear(in_dim,out_dim)
        self.backbone.remove_projection_header()
        for param in self.backbone.parameters():
            param.requires_grad = False
    
    def forward(self, x):
        # Extract features from the frozen backbone
        with torch.no_grad():  # Backbone is frozen
            features = self.backbone(x)
        return self.classifier(features)

    def training_step(self, batch, batch_idx):
        imgs,labels = batch
        imgs,labels = imgs.to(self.device),labels.to(self.device)
        preds = self.forward(imgs)
        loss = F.cross_entropy(preds, labels)
        return loss
    
    def test_step(self, batch, batch_idx):
        # Unpack the batch (input data and labels)
        imgs, labels = batch
        logits = self.forward(imgs)
        loss = F.cross_entropy(logits, labels)
        # Calculate top-1 accuracy
        acc1 = (logits.argmax(dim=1) == labels).float().mean()
        
        # Calculate top-5 accuracy
        top5 = torch.topk(logits, k=5, dim=1).indices
        acc5 = (top5 == labels.view(-1, 1)).float().sum(dim=1).mean()

        # Log both accuracies and the loss
        self.log('test_loss', loss, prog_bar=True)
        self.log('test_acc1', acc1, prog_bar=True)
        self.log('test_acc5', acc5, prog_bar=True)

        # Optionally return any metrics you want to save or use for other purposes
        return {'test_loss': loss, 'test_acc1': acc1, 'test_acc5':acc5}

    def configure_optimizers(self):
        if self.optim_name == "SGD":
            optimizer = optim.SGD(params=self.linear_net.parameters(),
                                  lr=self.hparams.lr,
                                  momentum=self.hparams.momentum,
                                  weight_decay=self.hparams.weight_decay)
        elif self.optim_name == "AdamW":
            optimizer = optim.AdamW(params=self.linear_net.parameters(),
                                  lr=self.hparams.lr,
                                  momentum=self.hparams.momentum,
                                  weight_decay=self.hparams.weight_decay)
        else:
            raise NotImplementedError("optimizer:"+ self.optimizer +" not implemented")
        scheduler = optim.lr_scheduler.MultiStepLR(optimizer=optimizer,
                                                   milestones=[self.hparams.n_epochs*0.6,
                                                               self.hparams.n_epochs*0.8],gamma=0.1)
        return [optimizer],[scheduler]
        
        
