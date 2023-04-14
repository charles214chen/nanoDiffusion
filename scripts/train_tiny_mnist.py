# !/usr/bin/env python3
# coding=utf-8
#
# All Rights Reserved
#
"""
Train a tiny model with mnist dataset, only using two labels: 0 1
Even with cpu couple of hours should be enough.

Authors: ChenChao (chenchao214@outlook.com)
"""
import argparse
import datetime
import torch
import wandb

from torch.utils.data import DataLoader
from ddpm import script_utils
from datasets.tiny_mnist import MnistDataset
from tools import file_utils


def main(args):
    device = args.device
    file_utils.mkdir(args.log_dir)
    num_labels = 2
    try:
        diffusion = script_utils.get_diffusion_from_args(args,
                                                         img_channels=1,
                                                         img_size=(28, 28),
                                                         num_classes=num_labels,
                                                         num_groups=2).to(device)
        optimizer = torch.optim.Adam(diffusion.parameters(), lr=args.learning_rate)
        # torch.compile(diffusion)  # may help. windows not support.

        if args.model_checkpoint is not None:
            diffusion.load_state_dict(torch.load(args.model_checkpoint))
        if args.optim_checkpoint is not None:
            optimizer.load_state_dict(torch.load(args.optim_checkpoint))

        if args.log_to_wandb:
            if args.project_name is None:
                raise ValueError("args.log_to_wandb set to True but args.project_name is None")

            wandb_runner = wandb.init(
                project=args.project_name,
                entity='chenchao214',
                config=vars(args),
                name=args.run_name,
            )
            wandb.watch(diffusion)

        batch_size = args.batch_size

        target_labels = list(range(num_labels))
        train_dataset = MnistDataset(is_train=True, target_labels=target_labels)

        test_dataset = MnistDataset(is_train=False, target_labels=target_labels)

        train_loader = script_utils.cycle(DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            drop_last=True,
            num_workers=0,
        ))
        test_loader = DataLoader(test_dataset, batch_size=batch_size, drop_last=True, num_workers=0)

        acc_train_loss = 0

        for iteration in range(1, args.iterations + 1):
            diffusion.train()

            x, y = next(train_loader)
            x = x.to(device)
            y = y.to(device)

            if args.use_labels:
                loss = diffusion(x, y)
            else:
                loss = diffusion(x)

            print(f"=====> iter: {iteration}, loss: {round(loss.item(), 6)}")

            acc_train_loss += loss.item()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            diffusion.update_ema()

            if iteration % args.log_rate == 0:
                test_loss = 0
                with torch.no_grad():
                    diffusion.eval()
                    for x, y in test_loader:
                        x = x.to(device)
                        y = y.to(device)

                        if args.use_labels:
                            loss = diffusion(x, y)
                        else:
                            loss = diffusion(x)

                        test_loss += loss.item()

                if args.use_labels:
                    samples = diffusion.sample(num_labels, device, y=torch.arange(2, device=device))
                else:
                    samples = diffusion.sample(num_labels, device)

                samples = ((samples + 1) / 2).clip(0, 1).permute(0, 2, 3, 1).numpy()

                test_loss /= len(test_loader)
                acc_train_loss /= args.log_rate
                if args.log_to_wandb:
                    wandb.log({
                        "test_loss": test_loss,
                        "train_loss": acc_train_loss,
                        "samples": [wandb.Image(sample) for sample in samples],
                    })

                acc_train_loss = 0
                print(f"---------> test loss: {round(test_loss, 6)}")

            if iteration % args.checkpoint_rate == 0:
                model_filename = f"{args.log_dir}/{args.project_name}-{args.run_name}-iteration-{iteration}-model.pth"
                optim_filename = f"{args.log_dir}/{args.project_name}-{args.run_name}-iteration-{iteration}-optim.pth"

                torch.save(diffusion.state_dict(), model_filename)
                torch.save(optimizer.state_dict(), optim_filename)

        if args.log_to_wandb:
            wandb_runner.finish()
    except KeyboardInterrupt:
        print("Keyboard interrupt, run finished early")
    finally:
        if args.log_to_wandb:
            wandb_runner.finish()


def create_argparser() -> argparse.Namespace:
    device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
    time_frame = datetime.datetime.now().strftime("ddpm-%Y-%m-%d-%H-%M")
    run_name = f"tiny_mnist_{time_frame}"
    defaults = dict(
        learning_rate=2e-4,
        batch_size=128,
        iterations=800000,
        log_to_wandb=False,
        log_rate=200,
        checkpoint_rate=800,
        log_dir="./checkpoints/nano2",
        project_name="aigc-ddpm",
        run_name=run_name,
        model_checkpoint=None,
        optim_checkpoint=None,
        schedule_low=1e-4,
        schedule_high=0.02,
        device=device,
    )
    defaults.update(nano_diffusion_defaults())

    parser = argparse.ArgumentParser()
    script_utils.add_dict_to_argparser(parser, defaults)
    return parser.parse_args()


def nano_diffusion_defaults():
    defaults = dict(
        num_timesteps=1000,
        schedule="linear",
        loss_type="l2",
        use_labels=True,
        base_channels=4,
        channel_mults=(1, 2),
        num_res_blocks=1,
        time_emb_dim=8,
        norm="gn",
        dropout=0.1,
        activation="silu",
        attention_resolutions=(1,),
        ema_decay=0.999,
        ema_update_rate=1,
    )

    return defaults


if __name__ == "__main__":
    args = create_argparser()
    for k, v in args.__dict__.items():
        print(f"===> {k} : {v}")
    main(args)
